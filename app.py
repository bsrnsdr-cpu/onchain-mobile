import time
from collections import Counter
from datetime import datetime, timezone
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title='Onchain Intelligence Mobile v1.4', page_icon='🔎', layout='wide')
st.title('🔎 Onchain Intelligence Mobile v1.4')
st.caption('Ücretsiz API taraması • Güvenlik ve fırsat skorları ön eleme amaçlıdır • Yatırım tavsiyesi değildir')
DEX='https://api.dexscreener.com'
GECKO='https://api.geckoterminal.com/api/v2'
NETWORKS={'solana':'solana','bsc':'bsc','base':'base'}
EVM={'bsc':'56','base':'8453'}

class APIError(Exception): pass

def fetch(url,params=None):
    try:
        r=requests.get(url,params=params,timeout=20,headers={'Accept':'application/json','User-Agent':'OnchainIntelligenceMobile/1.4'})
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as exc:
        raise APIError(f'{url}: {exc}') from exc

def n(x,default=0):
    try: return float(x) if x is not None else default
    except (TypeError,ValueError): return default

@st.cache_data(ttl=120,show_spinner=False)
def discover(chains, pages):
    items={}; errors=[]
    def add(chain,address,source):
        if chain not in chains or not address:return
        key=(chain,address)
        items.setdefault(key,{'chain':chain,'address':address,'sources':set()})['sources'].add(source)
    for source,route in [('profile','/token-profiles/latest/v1'),('boost','/token-boosts/latest/v1'),('top boost','/token-boosts/top/v1')]:
        try:
            data=fetch(DEX+route)
            for x in data if isinstance(data,list) else []: add(x.get('chainId'),x.get('tokenAddress'),source)
        except APIError as e: errors.append(str(e))
    # Public GeckoTerminal new-pools: limited pages, paced to respect public limits.
    for chain in chains:
        for page in range(1,pages+1):
            try:
                data=fetch(f'{GECKO}/networks/{NETWORKS[chain]}/new_pools',{'page':page,'include':'base_token'})
                included={x.get('id'):x for x in data.get('included',[])}
                for pool in data.get('data',[]):
                    rel=((pool.get('relationships') or {}).get('base_token') or {}).get('data') or {}
                    token_id=rel.get('id','')
                    token=included.get(token_id,{})
                    address=(token.get('attributes') or {}).get('address')
                    if not address and token_id.startswith(chain+'_'):
                        address=token_id[len(chain)+1:]
                    add(chain,address,'gecko new pool')
            except APIError as e: errors.append(str(e))
            time.sleep(1.2)
    return [{**v,'sources':', '.join(sorted(v['sources']))} for v in items.values()],errors

@st.cache_data(ttl=120,show_spinner=False)
def pairs(chain,address):
    data=fetch(f'{DEX}/token-pairs/v1/{chain}/{address}')
    return data if isinstance(data,list) else []

@st.cache_data(ttl=1800,show_spinner=False)
def security(chain,address):
    if chain=='solana':
        url='https://api.gopluslabs.io/api/v1/solana/token_security'
        key=address
    else:
        url=f'https://api.gopluslabs.io/api/v1/token_security/{EVM[chain]}'
        key=address.lower()
    data=fetch(url,{'contract_addresses':key})
    if str(data.get('code'))!='1':return None,'GoPlus yanıtı başarılı değil'
    result=data.get('result') or {}
    if isinstance(result,dict):
        obj=result.get(key) or result.get(address) or result.get(address.lower())
        if not obj and len(result)==1:obj=next(iter(result.values()))
    else: obj=None
    return (obj if isinstance(obj,dict) else None),''

def is_true(value): return value is True or str(value).lower() in ('1','true')

def risk_status(chain,record):
    if not isinstance(record,dict) or not record:return 'Bilinmiyor','API güvenlik verisi yok'
    if chain=='solana':
        critical=['non_transferable','default_account_state_frozen']
        caution=['mintable','freezable','closable','metadata_mutable','transfer_fee_upgradable','transfer_hook_upgradable']
    else:
        critical=['is_honeypot','cannot_sell_all','is_blacklisted','transfer_pausable','hidden_owner','owner_change_balance']
        caution=['is_mintable','can_take_back_ownership','is_proxy']
    flagged=[x for x in critical if is_true(record.get(x))]
    if flagged:return 'Kritik',', '.join(flagged)
    warned=[x for x in caution if is_true(record.get(x))]
    if warned:return 'Dikkat',', '.join(warned)
    inspected=sum(x in record for x in critical+caution)
    if not inspected:return 'Bilinmiyor','Yanıt geldi ancak tanınan kontrol alanı yok'
    return 'Kritik bayrak yok','Kontrol edilen alanlarda kritik bayrak görülmedi; güvenlik garantisi değildir'

def score(p):
    liq=n((p.get('liquidity') or {}).get('usd'));vol=n((p.get('volume') or {}).get('h24'))
    tx=(p.get('txns') or {}).get('h24') or {}; buys=n(tx.get('buys')); sells=n(tx.get('sells'))
    change=n((p.get('priceChange') or {}).get('h24')); ratio=vol/max(liq,1)
    return round(min(liq/100000,1)*30+min(vol/300000,1)*30+buys/max(buys+sells,1)*20+(10 if 0<ratio<8 else 0)+(10 if 0<change<100 else 0))


@st.cache_data(ttl=300,show_spinner=False)
def minute_volume(chain,pool_address):
    """Return completed 30/60 minute volume windows from GeckoTerminal 1m OHLCV.
    Missing/incomplete candles are not extrapolated."""
    if not pool_address:return None,'Havuz adresi yok'
    data=fetch(f'{GECKO}/networks/{NETWORKS[chain]}/pools/{pool_address}/ohlcv/minute',
               {'aggregate':1,'limit':240,'currency':'usd'})
    candles=(((data.get('data') or {}).get('attributes') or {}).get('ohlcv_list') or [])
    if not candles:return None,'Dakikalık OHLCV bulunamadı'
    now=int(time.time()); bucket=(now//60)*60
    by_time={int(c[0]):n(c[5]) for c in candles if isinstance(c,list) and len(c)>=6 and int(c[0])<bucket}
    def window(minutes_ago,length):
        stamps=[bucket-60*(i+1) for i in range(minutes_ago,minutes_ago+length)]
        # Some providers omit zero-volume candles; do not interpret missing as zero.
        if not all(t in by_time for t in stamps):return None
        return sum(by_time[t] for t in stamps)
    current30,previous30=window(0,30),window(30,30)
    current60,previous60=window(0,60),window(60,60)
    return (current30,previous30,current60,previous60),''

def growth(now,previous):
    if now is None or previous is None:return None
    if previous==0:return None  # no meaningful percentage denominator
    return round((now/previous-1)*100,1)

def holders_data(record):
    """GoPlus holder data may be missing or incomplete; do not imply full-chain coverage."""
    if not isinstance(record,dict):return None,None,'GoPlus holder verisi yok'
    count=record.get('holder_count')
    try:count=int(count) if count is not None else None
    except (ValueError,TypeError):count=None
    holders=record.get('holders')
    if not isinstance(holders,list) or len(holders)<10:
        return count,None,'İlk 10 holder payı için yeterli veri yok'
    percentages=[]
    for h in holders[:10]:
        if not isinstance(h,dict):return count,None,'Holder kayıtları eksik'
        try:
            raw=h.get('percent')
            if raw is None:return count,None,'Holder yüzdesi eksik'
            val=float(raw)
            if not 0<=val<=1:return count,None,'Holder yüzdesi formatı doğrulanamadı'
            percentages.append(val*100)
        except (TypeError,ValueError):return count,None,'Holder yüzdesi okunamadı'
    return count,round(sum(percentages),2),'GoPlus ilk 10 holder kaydı; cüzdanlar/LP/borsa ayrıştırılmadı'

def token_age_days(record):
    if not isinstance(record,dict):return None
    # GoPlus EVM records sometimes expose a Unix token creation timestamp.
    for key in ('create_time','creation_time'):
        raw=record.get(key)
        try:
            ts=float(raw)
            if ts>1e12:ts/=1000
            if 1230768000<ts<=time.time():return round((time.time()-ts)/86400,2)
        except (TypeError,ValueError):pass
    return None

def signal(p,risk,vol30growth,vol60growth,top10):
    """Rule-based screening, never a buy recommendation or forecast."""
    tx=(p.get('txns') or {}).get('h1') or {}
    buys,sells=n(tx.get('buys')),n(tx.get('sells'))
    ratio=buys/max(buys+sells,1)
    liq=n((p.get('liquidity') or {}).get('usd'))
    change=n((p.get('priceChange') or {}).get('h1'))
    reasons=[];points=0
    if buys+sells>=20 and ratio>=0.6:points+=2;reasons.append('1s alım ağırlığı')
    if vol30growth is not None and vol30growth>=30:points+=2;reasons.append('30dk hacim artışı')
    if vol60growth is not None and vol60growth>=30:points+=2;reasons.append('1s hacim artışı')
    if liq>=20000:points+=1;reasons.append('Likidite ≥20k$')
    if 0<change<20:points+=1;reasons.append('1s fiyat momentumu')
    if top10 is not None and top10>70:points-=2;reasons.append('Yüksek holder yoğunluğu')
    if risk=='Kritik':return 'Risk nedeniyle elendi','Doğrulanmış kritik bayrak'
    if risk in ('Bilinmiyor','Kontrol edilmedi'):points-=2;reasons.append('Güvenlik doğrulanamadı')
    if risk=='Dikkat':points-=1;reasons.append('Güvenlik uyarısı')
    if vol30growth is None and vol60growth is None:reasons.append('Hacim trendi eksik')
    label='Güçlü izleme' if points>=6 else 'İzleme' if points>=3 else 'Zayıf / veri eksik'
    return label,', '.join(reasons) or 'Yeterli sinyal yok'

with st.expander('⚙️ Filtreler',expanded=True):
    chains=st.multiselect('Ağlar',list(NETWORKS),default=list(NETWORKS))
    a,b=st.columns(2)
    with a:
        mc_min=st.number_input('Min market cap ($)',min_value=0,value=3000,step=1000)
        liq_min=st.number_input('Min likidite ($)',min_value=0,value=1000,step=1000)
        age_max=st.number_input('Maks havuz yaşı (gün)',min_value=1,value=30)
    with b:
        mc_max=st.number_input('Maks market cap ($)',min_value=0,value=1000000,step=100000)
        vol_min=st.number_input('Min 24s hacim ($)',min_value=0,value=1000,step=1000)
        min_score=st.slider('Min fırsat skoru',0,100,30)
    pages=st.slider('GeckoTerminal yeni havuz sayfası / ağ',1,3,1)
    limit=st.slider('En fazla detaylı taranacak token',10,100,40,10)
    check=st.checkbox('GoPlus güvenlik kontrolü (Solana/BSC/Base)',value=True)
    exclude=st.checkbox('Doğrulanmış kritik riskleri ele',value=True)
    advanced=st.checkbox('Detaylı hacim/holder/sinyal analizi (ek API sorguları)',value=True)
    run=st.button('🔍 Taramayı başlat',type='primary')

st.info('Yeni havuzlar + DEX profilleri/boost listeleri kullanılır. Tüm zinciri kapsamaz. Bilinmeyen güvenlik durumu güvenli demek değildir. Ücretsiz API kotaları değişebilir.')
if run:
    if not chains or mc_min>mc_max:st.error('Ağ ve market cap aralığını düzelt.');st.stop()
    candidates,api_errors=discover(tuple(chains),pages)
    # Rotate candidates across chains/sources rather than taking first N only.
    by_chain={c:[x for x in candidates if x['chain']==c] for c in chains}
    selected=[]
    while len(selected)<limit and any(by_chain.values()):
        for chain in chains:
            if by_chain[chain] and len(selected)<limit:selected.append(by_chain[chain].pop(0))
    counts=Counter(); rows=[]
    progress=st.progress(0)
    for i,item in enumerate(selected):
        try:
            ps=pairs(item['chain'],item['address'])
            if not ps:counts['Havuz bulunamadı']+=1;continue
            # Only use pairs whose base token matches the discovered address.
            matching=[p for p in ps if (p.get('baseToken') or {}).get('address','').lower()==item['address'].lower()]
            if not matching:counts['Base token eşleşmedi']+=1;continue
            p=max(matching,key=lambda x:n((x.get('liquidity') or {}).get('usd')))
            mc=p.get('marketCap'); created=p.get('pairCreatedAt')
            if mc is None:counts['Market cap eksik']+=1;continue
            if not created:counts['Havuz tarihi eksik']+=1;continue
            age=max(0,(time.time()*1000-n(created))/86400000)
            liq=n((p.get('liquidity') or {}).get('usd'));vol=n((p.get('volume') or {}).get('h24'));points=score(p)
            if not(mc_min<=n(mc)<=mc_max and liq>=liq_min and vol>=vol_min and age<=age_max and points>=min_score):
                counts['Piyasa filtresi']+=1;continue
            counts['Piyasa filtresini geçen']+=1
            risk,detail='Kontrol edilmedi','GoPlus kontrolü kapalı'
            sec=None
            if check:
                try:
                    sec,error=security(item['chain'],item['address'])
                    risk,detail=risk_status(item['chain'],sec)
                    if error:detail=error
                except APIError as e:risk,detail='Bilinmiyor',str(e);api_errors.append(str(e))
            counts['Güvenlik: '+risk]+=1
            if exclude and risk=='Kritik':counts['Kritik risk nedeniyle elenen']+=1;continue
            holder_count,top10,holder_note=holders_data(sec)
            token_age=token_age_days(sec)
            v30=prev30=v60=prev60=None
            volume_note='Detaylı analiz kapalı'
            if advanced:
                try:
                    (v30,prev30,v60,prev60),volume_note=minute_volume(item['chain'],p.get('pairAddress'))
                except APIError as e:
                    volume_note='Dakikalık hacim verisi alınamadı';api_errors.append(str(e))
            g30=growth(v30,prev30);g60=growth(v60,prev60)
            opportunity,signal_note=signal(p,risk,g30,g60,top10)
            rows.append({'Ağ':item['chain'],'Token':(p.get('baseToken') or {}).get('symbol','?'),'Adres':item['address'],
                         'Token yaşı (gün)':token_age,'Havuz yaşı (gün)':round(age,2),
                         'Holder sayısı':holder_count,'İlk 10 holder payı (%)':top10,'Holder veri notu':holder_note,
                         '30dk hacim ($)':round(v30,2) if v30 is not None else None,
                         'Önceki 30dk hacim ($)':round(prev30,2) if prev30 is not None else None,
                         '30dk hacim değişimi (%)':g30,
                         '1s hacim ($)':round(v60,2) if v60 is not None else None,
                         'Önceki 1s hacim ($)':round(prev60,2) if prev60 is not None else None,
                         '1s hacim değişimi (%)':g60,'Hacim veri notu':volume_note,
                         'Alım fırsatı sinyali':opportunity,'Sinyal gerekçesi':signal_note,
                         'Smart money net akımı ($)':None,'Smart money durumu':'Doğrulanmış etiketli cüzdan verisi yok',
                         'Market cap ($)':n(mc),'Likidite ($)':liq,'Hacim 24s ($)':vol,
                         'Fırsat skoru':points,'Güvenlik':risk,'Risk detayı':detail,'Kaynak':item['sources'],'DEX URL':p.get('url','')})
        except APIError as e:counts['Veri hatası']+=1;api_errors.append(str(e))
        finally:progress.progress((i+1)/max(len(selected),1))
    st.subheader('📋 Tarama teşhis raporu')
    diagnostic={'Keşfedilen benzersiz token':len(candidates),'Detaylı taranan':len(selected),'Sonuç listesine giren':len(rows),**counts}
    st.dataframe(pd.DataFrame([{'Aşama':k,'Adet':v} for k,v in diagnostic.items()]),hide_index=True,use_container_width=True)
    if rows:
        df=pd.DataFrame(rows)
        # Ranking penalizes uncertainty, does not falsely classify it as safe.
        penalties={'Kritik':50,'Dikkat':20,'Bilinmiyor':25,'Kontrol edilmedi':30,'Kritik bayrak yok':0}
        df['Öncelik puanı']=df.apply(lambda r:max(0,r['Fırsat skoru']-penalties.get(r['Güvenlik'],25)),axis=1)
        df=df.sort_values(['Öncelik puanı','Likidite ($)'],ascending=False)
        st.caption('30dk/1s hacim değişimi: önceki eşit süreli pencereye göre. Boş alan = doğrulanmış veri yok. Token yaşı, havuz yaşından farklıdır.')
        st.success(f'{len(df)} token listelendi.')
        if df['Güvenlik'].isin(['Bilinmiyor','Kontrol edilmedi']).any():st.warning('Bazı tokenların güvenliği doğrulanamadı; yatırım için güvenli oldukları söylenemez.')
        st.dataframe(df,hide_index=True,use_container_width=True,column_config={'DEX URL':st.column_config.LinkColumn('DEX bağlantısı')})
        st.download_button('⬇️ CSV indir',df.to_csv(index=False).encode('utf-8-sig'),'onchain_v14.csv','text/csv')
    else:st.warning('Bu taramada sonuç bulunamadı. Teşhis raporunu incele.')
    if api_errors:
        st.warning(f'{len(api_errors)} API hatası oluştu; tarama eksik olabilir.')
        with st.expander('API hata ayrıntıları'):st.code('\n'.join(api_errors[:20]))
st.caption('Smart money net akımı, doğrulanmış etiketli cüzdan kaynağı olmadan hesaplanmaz. GoPlus holder verisi eksik veya token hesaplarını içeriyor olabilir. Otomatik emir ve 7/24 tarama yoktur.')
