import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests
import streamlit as st

BASE = 'https://api.dexscreener.com'
DB = Path('/tmp/onchain_mobile_snapshots.db')  # Geçici bulut depolaması; kalıcı değildir
CHAINS = {'solana': None, 'bsc': '56', 'base': '8453'}

st.set_page_config(page_title='Onchain Intelligence Mobile', layout='wide', page_icon='📊', initial_sidebar_state='collapsed')
st.markdown('''<style> .block-container {padding-top:1.1rem;padding-left:1rem;padding-right:1rem} div[data-testid="stMetric"] {background:#182332;padding:12px;border-radius:12px} @media(max-width:640px){h1{font-size:1.65rem!important} [data-testid="stDataFrame"]{font-size:12px}} </style>''', unsafe_allow_html=True)
st.title('📊 Onchain Intelligence Mobile')
st.caption('Ücretsiz veri kaynakları • Gerçek zamanlı işlem sistemi değil • Yatırım tavsiyesi değildir')

def get_json(url, params=None):
    r = requests.get(url, params=params, timeout=18, headers={'User-Agent':'OnchainFreeMVP/1.0'})
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=120, show_spinner=False)
def discover():
    profiles = get_json(BASE + '/token-profiles/latest/v1')
    boosts = get_json(BASE + '/token-boosts/latest/v1')
    found = {}
    for source, items in [('profile', profiles), ('boost', boosts)]:
        for item in items if isinstance(items, list) else []:
            chain, address = item.get('chainId'), item.get('tokenAddress')
            if chain in CHAINS and address:
                key = (chain, address)
                found.setdefault(key, {'chain':chain, 'address':address, 'sources':set()})['sources'].add(source)
    return [{**v, 'sources': ', '.join(sorted(v['sources']))} for v in found.values()]

@st.cache_data(ttl=120, show_spinner=False)
def token_pairs(chain, address):
    data = get_json(f'{BASE}/token-pairs/v1/{chain}/{address}')
    return data if isinstance(data, list) else []

@st.cache_data(ttl=3600, show_spinner=False)
def security(chain, address):
    chain_id = CHAINS[chain]
    if not chain_id:
        return None, 'Solana güvenlik kontrolü bu sürümde entegre değil'
    data = get_json(f'https://api.gopluslabs.io/api/v1/token_security/{chain_id}', {'contract_addresses':address.lower()})
    if str(data.get('code')) != '1':
        return None, 'GoPlus sonuç döndürmedi'
    result = data.get('result') or {}
    return result.get(address.lower()) or result.get(address) or None, ''

def num(x):
    try: return float(x or 0)
    except (ValueError, TypeError): return 0.0

def classify_security(s):
    if s is None: return 'Bilinmiyor', 'Güvenlik verisi yok'
    critical = ['is_honeypot','cannot_sell_all','is_blacklisted','transfer_pausable','hidden_owner']
    flags = [k for k in critical if str(s.get(k,'')) == '1']
    if flags: return 'Kritik', ', '.join(flags)
    caution = [k for k in ['is_mintable','can_take_back_ownership','owner_change_balance'] if str(s.get(k,'')) == '1']
    if caution: return 'Dikkat', ', '.join(caution)
    return 'Belirgin kritik bayrak yok', 'GoPlus sınırlı kontrol; güvenli olduğu anlamına gelmez'

def score(p):
    liq = num((p.get('liquidity') or {}).get('usd'))
    vol = num((p.get('volume') or {}).get('h24'))
    tx = (p.get('txns') or {}).get('h24') or {}
    buys, sells = num(tx.get('buys')), num(tx.get('sells'))
    change = num((p.get('priceChange') or {}).get('h24'))
    ratio = vol / max(liq, 1)
    # Heuristic screening score, not a predictive model.
    points = (min(liq / 100000, 1) * 30 + min(vol / 300000, 1) * 30
              + (min(buys / max(buys+sells, 1), 1) * 20)
              + (10 if 0 < ratio < 8 else 0)
              + (10 if 0 < change < 100 else 0))
    return round(points)

def init_db():
    with sqlite3.connect(DB) as c:
        c.execute('CREATE TABLE IF NOT EXISTS snapshots (timestamp TEXT, chain TEXT, address TEXT, symbol TEXT, price REAL, liquidity REAL, volume REAL, score INTEGER, risk TEXT)')

def save_rows(rows):
    init_db()
    with sqlite3.connect(DB) as c:
        c.executemany('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)', [
            (datetime.now(timezone.utc).isoformat(), r['Ağ'], r['Adres'], r['Token'], r['Fiyat ($)'], r['Likidite ($)'], r['Hacim 24s ($)'], r['Skor'], r['Güvenlik']) for r in rows
        ])

with st.expander('⚙️ Tarama filtreleri', expanded=True):
    st.header('Filtreler')
    chains = st.multiselect('Ağlar', list(CHAINS), default=list(CHAINS))
    mc_min = st.number_input('Minimum market cap ($)', min_value=0, value=50000, step=10000)
    mc_max = st.number_input('Maksimum market cap ($)', min_value=0, value=1000000, step=100000)
    liq_min = st.number_input('Minimum likidite ($)', min_value=0, value=20000, step=5000)
    vol_min = st.number_input('Minimum 24s hacim ($)', min_value=0, value=100000, step=10000)
    age_max = st.number_input('Maksimum havuz yaşı (gün)', min_value=1, value=30)
    min_score = st.slider('Minimum fırsat skoru', 0, 100, 40)
    exclude_critical = st.checkbox('Kritik güvenlik bayraklarını ele', value=True)
    check_security = st.checkbox('GoPlus güvenlik kontrolü (BSC/Base)', value=True)
    max_tokens = st.slider('Tarama adedi (ücretsiz API dostu)', 5, 40, 15, 5)
    run = st.button('🔍 Canlı verileri tara', type='primary')

st.info('☁️ Bulut sürümünde tarama kayıtları geçicidir; uygulama yeniden başlatılırsa kaybolabilir. CSV indirerek sakla. Otomatik 7/24 tarama yoktur.')
st.info('Keşif kapsamı DEX Screener son token profilleri ve boost listeleriyle sınırlıdır; tüm yeni tokenları kapsamaz. Market cap verisi olmayan tokenlar elenir. Havuz yaşı token yaşı değildir.')
if run:
    if not chains or mc_min > mc_max:
        st.error('Ağ seç ve market cap aralığını düzelt.')
        st.stop()
    try:
        candidates = [x for x in discover() if x['chain'] in chains][:max_tokens]
    except requests.RequestException as e:
        st.error(f'Keşif API hatası: {e}')
        st.stop()
    rows, errors = [], []
    progress = st.progress(0)
    for i, token in enumerate(candidates):
        try:
            pairs = token_pairs(token['chain'], token['address'])
            # Prefer pool with largest USD liquidity for this token.
            if not pairs: continue
            p = max(pairs, key=lambda x:num((x.get('liquidity') or {}).get('usd')))
            mc_raw = p.get('marketCap')
            if mc_raw is None: continue
            mc, liq, vol = num(mc_raw), num((p.get('liquidity') or {}).get('usd')), num((p.get('volume') or {}).get('h24'))
            created = p.get('pairCreatedAt')
            if not created: continue
            age = max(0, (time.time() * 1000 - num(created)) / 86400000)
            points = score(p)
            if not (mc_min <= mc <= mc_max and liq >= liq_min and vol >= vol_min and age <= age_max and points >= min_score): continue
            risk, reason = 'Kontrol edilmedi', 'GoPlus kapalı'
            if check_security:
                try:
                    data, err = security(token['chain'], token['address'])
                    risk, reason = classify_security(data)
                    if err: reason = err
                except requests.RequestException as e:
                    risk, reason = 'Bilinmiyor', f'GoPlus API hatası: {e}'
            if exclude_critical and risk in ('Kritik', 'Bilinmiyor', 'Kontrol edilmedi'): continue
            rows.append({'Ağ':token['chain'], 'Token':(p.get('baseToken') or {}).get('symbol','?'), 'Adres':token['address'], 'Market cap ($)':mc,
                         'Likidite ($)':liq, 'Hacim 24s ($)':vol, 'Fiyat ($)':num(p.get('priceUsd')),
                         'Havuz yaşı (gün)':round(age,1), 'Skor':points, 'Güvenlik':risk,
                         'Risk detayı':reason, 'Keşif':token['sources'], 'DEX URL':p.get('url','')})
        except (requests.RequestException, ValueError, KeyError) as e:
            errors.append(f"{token['chain']} {token['address']}: {e}")
        finally:
            progress.progress((i+1)/max(len(candidates),1))
    if rows:
        try:
            save_rows(rows)
        except (OSError, sqlite3.Error) as e:
            st.warning(f'Geçici kayıt yazılamadı: {e}')
        df = pd.DataFrame(rows).sort_values('Skor', ascending=False)
        st.success(f'{len(df)} token filtreyi geçti. CSV indirerek kalıcı saklayabilirsin.')
        st.dataframe(df, use_container_width=True, hide_index=True, column_config={'DEX URL':st.column_config.LinkColumn('DEX bağlantısı')})
        st.download_button('CSV indir', df.to_csv(index=False).encode('utf-8-sig'), 'onchain_scan.csv', 'text/csv')
    else:
        st.warning('Bu taramada filtreyi geçen token bulunamadı. Kriterleri gevşetebilir veya daha sonra yeniden tarayabilirsin.')
    if errors:
        st.warning(f'{len(errors)} token için veri alınamadı; sonuçlar eksik olabilir.')
        with st.expander('API hata detayları'):
            st.code('\n'.join(errors[:20]))

st.divider()
st.subheader('Kaydedilmiş taramalar')
try:
    init_db()
    with sqlite3.connect(DB) as c:
        history = pd.read_sql_query('SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 250', c)
except (OSError, sqlite3.Error):
    history = pd.DataFrame()
if len(history):
    st.dataframe(history, use_container_width=True, hide_index=True)
else:
    st.caption('Henüz kayıt yok. İlk taramayı başlat.')
st.caption('Bulut ortamı uykuya geçebilir. Bu uygulama açıkken elle tarama yapar; otomatik emir göndermez. Smart money, holder sayısı ve gerçek zamanlı balina izleme bu sürümde yoktur.')
