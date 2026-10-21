import time
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

BASE = 'https://api.dexscreener.com'
DB = Path('/tmp/onchain_mobile_snapshots.db')
CHAINS = {'solana': None, 'bsc': '56', 'base': '8453'}

st.set_page_config(page_title='Onchain Intelligence Mobile', layout='wide', page_icon='📊', initial_sidebar_state='collapsed')
st.markdown('''<style>.block-container{padding-top:1.1rem;padding-left:1rem;padding-right:1rem}div[data-testid="stMetric"]{background:#182332;padding:12px;border-radius:12px}@media(max-width:640px){h1{font-size:1.65rem!important}[data-testid="stDataFrame"]{font-size:12px}}</style>''', unsafe_allow_html=True)
st.title('📊 Onchain Intelligence Mobile')
st.caption('v1.2 • Ücretsiz veri kaynakları • Yatırım tavsiyesi değildir')


def get_json(url, params=None):
    response = requests.get(url, params=params, timeout=18, headers={'User-Agent': 'OnchainFreeMVP/1.2'})
    response.raise_for_status()
    return response.json()


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
                found.setdefault(key, {'chain': chain, 'address': address, 'sources': set()})['sources'].add(source)
    return [{**v, 'sources': ', '.join(sorted(v['sources']))} for v in found.values()]


@st.cache_data(ttl=120, show_spinner=False)
def token_pairs(chain, address):
    data = get_json(f'{BASE}/token-pairs/v1/{chain}/{address}')
    return data if isinstance(data, list) else []


@st.cache_data(ttl=3600, show_spinner=False)
def security(chain, address):
    chain_id = CHAINS[chain]
    if chain_id is None:
        return None, 'Solana güvenlik kontrolü bu sürümde entegre değil'
    data = get_json(f'https://api.gopluslabs.io/api/v1/token_security/{chain_id}', {'contract_addresses': address.lower()})
    if str(data.get('code')) != '1':
        return None, 'GoPlus sonuç döndürmedi'
    result = data.get('result') or {}
    return result.get(address.lower()) or result.get(address) or None, ''


def num(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def classify_security(data):
    if not isinstance(data, dict) or not data:
        return 'Bilinmiyor', 'Güvenlik verisi yok'
    critical = ['is_honeypot', 'cannot_sell_all', 'is_blacklisted', 'transfer_pausable', 'hidden_owner']
    flags = [key for key in critical if str(data.get(key, '')) == '1']
    if flags:
        return 'Kritik', ', '.join(flags)
    caution = ['is_mintable', 'can_take_back_ownership', 'owner_change_balance']
    flags = [key for key in caution if str(data.get(key, '')) == '1']
    if flags:
        return 'Dikkat', ', '.join(flags)
    return 'Belirgin kritik bayrak yok', 'Kontrol edilen alanlarda kritik bayrak bulunmadı; güvenlik garantisi değildir'


def score(pair):
    liq = num((pair.get('liquidity') or {}).get('usd'))
    vol = num((pair.get('volume') or {}).get('h24'))
    tx = (pair.get('txns') or {}).get('h24') or {}
    buys, sells = num(tx.get('buys')), num(tx.get('sells'))
    change = num((pair.get('priceChange') or {}).get('h24'))
    ratio = vol / max(liq, 1)
    return round(min(liq / 100000, 1) * 30 + min(vol / 300000, 1) * 30 + min(buys / max(buys + sells, 1), 1) * 20 + (10 if 0 < ratio < 8 else 0) + (10 if 0 < change < 100 else 0))


def init_db():
    with sqlite3.connect(DB) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS snapshots (timestamp TEXT, chain TEXT, address TEXT, symbol TEXT, price REAL, liquidity REAL, volume REAL, score INTEGER, risk TEXT)')


def save_rows(rows):
    init_db()
    with sqlite3.connect(DB) as connection:
        connection.executemany('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)', [(datetime.now(timezone.utc).isoformat(), row['Ağ'], row['Adres'], row['Token'], row['Fiyat ($)'], row['Likidite ($)'], row['Hacim 24s ($)'], row['Skor'], row['Güvenlik']) for row in rows])


with st.expander('⚙️ Tarama filtreleri', expanded=True):
    st.header('Filtreler')
    chains = st.multiselect('Ağlar', list(CHAINS), default=list(CHAINS))
    mc_min = st.number_input('Minimum market cap ($)', min_value=0, value=50000, step=10000)
    mc_max = st.number_input('Maksimum market cap ($)', min_value=0, value=1000000, step=100000)
    liq_min = st.number_input('Minimum likidite ($)', min_value=0, value=20000, step=5000)
    vol_min = st.number_input('Minimum 24s hacim ($)', min_value=0, value=100000, step=10000)
    age_max = st.number_input('Maksimum havuz yaşı (gün)', min_value=1, value=30)
    min_score = st.slider('Minimum fırsat skoru', 0, 100, 40)
    exclude_critical = st.checkbox('Doğrulanmış kritik güvenlik bayraklarını ele', value=True)
    check_security = st.checkbox('GoPlus güvenlik kontrolü (BSC/Base)', value=True)
    max_tokens = st.slider('Tarama adedi (ücretsiz API dostu)', 5, 40, 15, 5)
    run = st.button('🔍 Canlı verileri tara', type='primary')

st.info('Bilinmiyor = güvenli değil; doğrulanamayan tokenlar uyarıyla listelenir. Solana güvenlik kontrolü henüz entegre değil. Keşif tüm tokenları kapsamaz. Bulut kayıtları geçicidir.')

if run:
    if not chains or mc_min > mc_max:
        st.error('Ağ seç ve market cap aralığını düzelt.')
        st.stop()
    try:
        discovered = [item for item in discover() if item['chain'] in chains]
        candidates = discovered[:max_tokens]
    except (requests.RequestException, ValueError) as exc:
        st.error(f'Keşif API hatası: {exc}')
        st.stop()

    rows, errors = [], []
    counts = Counter()
    counts['Keşfedilen aday'] = len(discovered)
    counts['Tarama limitine alınan'] = len(candidates)
    progress = st.progress(0)
    for i, token in enumerate(candidates):
        try:
            pairs = token_pairs(token['chain'], token['address'])
            if not pairs:
                counts['Havuz verisi yok'] += 1
                continue
            pair = max(pairs, key=lambda item: num((item.get('liquidity') or {}).get('usd')))
            mc_raw = pair.get('marketCap')
            if mc_raw is None:
                counts['Market cap verisi yok'] += 1
                continue
            mc = num(mc_raw)
            liq = num((pair.get('liquidity') or {}).get('usd'))
            vol = num((pair.get('volume') or {}).get('h24'))
            created = pair.get('pairCreatedAt')
            if not created:
                counts['Havuz yaşı verisi yok'] += 1
                continue
            age = max(0, (time.time() * 1000 - num(created)) / 86400000)
            points = score(pair)
            if not (mc_min <= mc <= mc_max and liq >= liq_min and vol >= vol_min and age <= age_max and points >= min_score):
                counts['Piyasa filtrelerinden elenen'] += 1
                continue
            counts['Piyasa filtrelerini geçen'] += 1
            risk, reason = 'Kontrol edilmedi', 'Güvenlik kontrolü kapalı'
            if check_security:
                try:
                    data, err = security(token['chain'], token['address'])
                    risk, reason = classify_security(data)
                    if err:
                        reason = err
                except (requests.RequestException, ValueError) as exc:
                    risk, reason = 'Bilinmiyor', f'Güvenlik API hatası: {exc}'
            counts[f'Güvenlik: {risk}'] += 1
            # Unknown/unverified does NOT mean critical. Exclude only confirmed critical flags.
            if exclude_critical and risk == 'Kritik':
                counts['Kritik risk nedeniyle elenen'] += 1
                continue
            rows.append({'Ağ': token['chain'], 'Token': (pair.get('baseToken') or {}).get('symbol', '?'), 'Adres': token['address'], 'Market cap ($)': mc, 'Likidite ($)': liq, 'Hacim 24s ($)': vol, 'Fiyat ($)': num(pair.get('priceUsd')), 'Havuz yaşı (gün)': round(age, 1), 'Skor': points, 'Güvenlik': risk, 'Risk detayı': reason, 'Keşif': token['sources'], 'DEX URL': pair.get('url', '')})
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{token['chain']} {token['address']}: {exc}")
            counts['İşleme hatası'] += 1
        finally:
            progress.progress((i + 1) / max(len(candidates), 1))

    counts['Sonuç listesine giren'] = len(rows)
    st.subheader('📋 Tarama teşhis raporu')
    st.dataframe(pd.DataFrame([{'Aşama': key, 'Adet': value} for key, value in counts.items()]), hide_index=True, use_container_width=True)
    if rows:
        try:
            save_rows(rows)
        except (OSError, sqlite3.Error) as exc:
            st.warning(f'Geçici kayıt yazılamadı: {exc}')
        df = pd.DataFrame(rows).sort_values('Skor', ascending=False)
        st.success(f'{len(df)} token filtreyi geçti.')
        if df['Güvenlik'].isin(['Bilinmiyor', 'Kontrol edilmedi']).any():
            st.warning('Listede güvenliği doğrulanmamış tokenlar var. Bilinmiyor veya kontrol edilmedi durumunu güvenli olarak yorumlama.')
        st.dataframe(df, use_container_width=True, hide_index=True, column_config={'DEX URL': st.column_config.LinkColumn('DEX bağlantısı')})
        st.download_button('CSV indir', df.to_csv(index=False).encode('utf-8-sig'), 'onchain_scan.csv', 'text/csv')
    else:
        st.warning('Bu taramada sonuç bulunamadı. Teşhis tablosunda hangi aşamada elendiğini incele.')
    if errors:
        st.warning(f'{len(errors)} token için veri alınamadı.')
        with st.expander('API hata detayları'):
            st.code('\n'.join(errors[:20]))

st.divider()
st.subheader('Kaydedilmiş taramalar')
try:
    init_db()
    with sqlite3.connect(DB) as connection:
        history = pd.read_sql_query('SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 250', connection)
except (OSError, sqlite3.Error):
    history = pd.DataFrame()
if len(history):
    st.dataframe(history, use_container_width=True, hide_index=True)
else:
    st.caption('Henüz kayıt yok. İlk taramayı başlat.')
st.caption('Elle tarama yapar; otomatik emir göndermez. Smart money ve gerçek zamanlı balina takibi bu sürümde yoktur.')
