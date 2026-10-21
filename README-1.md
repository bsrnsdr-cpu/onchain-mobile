# Onchain Intelligence Mobile — Ücretsiz Bulut MVP

Solana / BSC / Base token keşfi ve filtreleme için Streamlit Community Cloud'a hazır, Android Chrome uyumlu uygulama.

## Yalnızca Android telefonundan kurulum

1. Chrome ile https://github.com/signup adresinden ücretsiz GitHub hesabı aç veya giriş yap.
2. https://github.com/new adresine gir; `onchain-mobile` adlı yeni bir repository oluştur. Public seçeneği ücretsiz ve kolay başlangıç içindir. Kaynak kodun herkese açık olacağını unutma. `Create repository` seç.
3. Repository sayfasında `Add file` > `Upload files` seç. Bu ZIP'i **önce çıkar**. ZIP'in içindeki `app.py`, `requirements.txt`, `.gitignore`, `README.md` dosyalarını yükle. GitHub mobil web arayüzü klasör yüklemeye izin vermezse `.streamlit/config.toml` dosyasını ayrıca `Add file` > `Create new file` yoluyla oluştur; dosya adı alanına `.streamlit/config.toml` yazıp içeriğini bu paketten kopyala. Bu yapılandırma dosyası isteğe bağlıdır, yüklemezsen uygulama varsayılan tema ile çalışır.
4. `Commit changes` ile kaydet. GitHub mobil arayüzünde butonlar gizleniyorsa Chrome üç nokta menüsünden `Masaüstü sitesi`ni aç.
5. https://share.streamlit.io/ adresine Chrome ile git. GitHub ile giriş yap ve erişim izni ver.
6. `Create app` > `Yup, I have an app` seç. Repository olarak `KULLANICI_ADIN/onchain-mobile`, branch `main`, main file path `app.py` gir; `Deploy` seç.
7. Kurulum tamamlandığında sana özel `https://...streamlit.app` adresi açılır. Chrome üç nokta > `Ana ekrana ekle` ile kısayol oluştur.

## Önemli sınırlamalar

- Streamlit Community Cloud 12 saat trafik olmayan uygulamaları uykuya alabilir. Bu **7/24 tarayıcı değildir**. Uygulamayı açıp `Canlı verileri tara` butonuna dokunman gerekir.
- SQLite kayıtları `/tmp` altında geçicidir, yeniden başlatmalarda silinebilir. Sonuçları CSV indirerek sakla.
- DEX Screener keşfi yalnızca profil/boost listelerini kapsar; tüm tokenları kapsamaz.
- Market cap olmayan ve havuz tarihi olmayan tokenlar elenir.
- Solana GoPlus güvenlik kontrolü entegre değil. BSC/Base güvenlik verisi yoksa `Kritik güvenlik bayraklarını ele` seçeneği açıkken elenir. Bu seçeneği kapatmak riski artırır.
- Fırsat skoru basit heuristiktir; smart money, gerçek balina analizi, holder sayısı, otomatik emir, Telegram bildirimleri henüz yoktur.
- Herhangi bir API anahtarı veya cüzdan seed phrase'i girmen gerekmez. Kimseyle seed phrase paylaşma.
- Ücretsiz API'ler oran sınırı veya erişim hatası verebilir.

## Dosyalar

- `app.py`: uygulama
- `requirements.txt`: Python bağımlılıkları
- `.streamlit/config.toml`: mobil uyumlu koyu tema
- `.gitignore`: hassas/yerel dosyaları Git'e göndermeme

Resmi rehber: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
