# ThatsMyQuant — ilk ürün dilimi

12 Eylül 2026. PRODUCT.md §10'un ilk üç adımını başlatan yerel uygulama teslimi.
Bu rapor bütün ürün yönünün tamamlandığı anlamına gelmez.

## Çalışan akış

- Mevcut React/Vite ve FastAPI üzerinde açık tema, yerel IBM Plex fontları,
  responsive navigasyon, fiyat/hacim grafiği, strateji kuralları ve karar günlüğü.
- Anahtarsız piyasa keşfi; hesap kayıtları için ayrı operatör erişim kodu.
- Hazır sorular ve serbest metin Claude'a gider; model altı salt okunur uygulama
  aracıyla (`get_market_overview`, `get_strategy`, `get_decision_funnel`,
  `get_risk_summary`, `get_recent_fills`, `get_run_status`) aynı servisleri okur.
  Yazma aracı yoktur: emir, taslak, run başlatma veya limit değiştirme yolu bulunmaz.
  Risk/PnL modele hesaplatılmaz; hesaplanmış değerler aktarılır.
- Anahtar yoksa veya model çağrısı başarısızsa deterministik okuyucuya düşülür ve
  cevabın hangi motorla üretildiği UI'da yazar.
- Cevap SSE ile akar: çalışan gerçek araç aşaması anlık görünür, ardından kayıtlı iz
  (araç adı, süre, başarı/hata), model, tur sayısı ve token kullanımı gösterilir.
- Hesap kapsamındaki sorular operatör oturumu ister; oturumsuz seansta hesap araçları
  hem modele verilmez hem de çağrılırsa reddedilir.
- Sohbet geçmişi API sürecinde tutulur (DB havuzları salt okunur kalsın diye);
  yeniden başlatınca silinir. PostgreSQL'e sohbet/araç izi yazımı yapılmadı.
- Mevcut worker run'ı test/paper kaydından ayrılır. Tekrar değerlendirmeler,
  farklı parite/mumlar ve episode sayıları ayrı gösterilir.
- Canlı ledger fill/fee görünümü; farklı fee para birimleri toplanıp USDT denmez.
  Açık risk metrikleri ilk risk bazıdır; güncel koruma garantisi değildir.
- Başlangıç referansı ile çalışan IOC + tam miktar OCO çıkışı ayrı açıklanır.
- API havuzları DB seviyesinde salt okunurdur. UI/session uçları worker'ı veya
  canlı konfigürasyonu değiştirmez. Prod deployment/restart/migration yapılmadı.

## Güvenlik ve sınırlar

Host allowlist, Origin kontrolü, HttpOnly/SameSite operatör cookie'si, sekiz saatlik
süre ve kısa süreli giriş denemesi sınırı var. APP_OPERATOR_TOKEN rotasyonu eski
cookie'leri geçersiz kılar. Bu, loopback üzerinde tek operatör içindir; internet
servisi olarak sunulacak kullanıcı/yetki modeli değildir. API token'ı yoksa hesap
uçları kapalı kalır; piyasa keşfi çalışır. Session logout cookie'yi siler; sunucu
tarafında tek cookie revocation listesi yoktur (token rotasyonu tümünü kapatır).

Mevcut borsa sırları plaintext env dosyasından ATK alt sürecine aktarılır. ATK
profiline taşıma, şifreli saklama ve venue izin doğrulaması yapılmış sayılmaz.
Public market yanıtı risk sizing ve özel hesap durumunu dışarı vermez.

## Sonraki ürün adımları

1. Kalıcı Strategy/StrategyVersion, desteklenen tek değişiklikli taslak editörü.
2. Bağımsız simüle envanterle tek gölge run; kalıcı idempotency ve gerçek heartbeat.
3. Sohbet/araç çağrısı geçmişinin PostgreSQL'e yazılması (ayrı yazılabilir havuz
   gerektirir; LLM bağlantısının kendisi tamamlandı).
4. Kalıcı ATK çağrı izi, model/config sürümü ve bütün demo senaryoları.
5. Mevcut canlı çıkış yönetimi/mutabakat eksiklerinin execution kabul kapılarıyla
   tamamlanması. İlk ürün dilimi bu eksikleri çözmüş gibi göstermez.

Deneyler ekranı henüz durum açıklamasıdır; taslak/gölge çalıştırma düğmesi veya
uydurulmuş simülasyon sonucu yoktur. Model bu eylemleri isteyen soruya "bu sürümde
bağlı değil" cevabı verir. Varsayılan model `claude-haiku-4-5` (en ucuz güncel
model); `LLM_MODEL=claude-opus-5` daha güçlü akıl yürütme için değiştirilebilir.
Model cevaplarının doğruluğu araç verisiyle sınırlıdır; yanlış yorum ihtimali
ortadan kalkmaz, bu yüzden her cevabın altında gerçek araç izi durur.

## Doğrulama

- İzole yerel PostgreSQL üzerinde mevcut testler geçti; sohbet katmanı için 16 yeni
  test eklendi (araç kapsamı, tur bütçesi, araç hatası, fallback, oturum ayrımı,
  effort parametresinin modele göre gönderilmesi). Prod test yazımı yapılmadı.
- Altı aracın tamamı canlı prod kayıtlarıyla salt okunur çalıştırıldı (run 587,
  588 değerlendirme, gerçek SOL-USDT fill). Araç yükleri 0,6–4,4 KB.
- Canary taraması: OKX anahtar/secret/passphrase ve DB parolası araç yüklerinde ve
  modele giden istekte yok. Model çağrısı stub'lanarak akış uçtan uca doğrulandı;
  gerçek Claude çağrısı anahtar eklendiğinde `scripts/chat_smoke.py` ile denenir.
- Mevcut E2E testlerinin canlı poller ve instrument tablosuna örtük bağımlılığı
  fixture verisiyle giderildi.
- Prod kayıtları yeni API üzerinden salt okunur sorgulandı. 586 numaralı live run,
  SOL-USDT gerçek fill'i, farklı mum sayıları ve başlangıç mutabakatı doğrulandı.
- Operatör oturumu, yetkisiz özel veri reddi, kötü Host/Origin, token rotasyonu,
  desteklenmeyen komutların eylem üretmemesi ve sıfır kararın doğru açıklaması test edildi.
- 1440×900 ve 1366×768 masaüstü, 390 px mobil gerçek render'ları incelendi;
  document scrollWidth viewport ile eşleşti. Yerel IBM Plex fontu yüklendi.
- Mobil sohbet aç/kapat, taslak koruma, Enter ile serbest soru, Escape ile kapanma
  ve odağın açma düğmesine dönmesi doğrulandı. Mobil drawer focus döngüsü eklendi.
- Native %200 zoom in-app browser kısayoluyla uygulanamadı; bu kabul maddesi ve
  bütün hata/UNKNOWN/LLM-timeout görsel matrisi henüz tamamlanmadı. WCAG uyumu iddiası yok.
- Public market canary sizing/gate sızıntı kontrolü geçti. API pool yazma denemesi
  izole DB'de PostgreSQL ReadOnlySQLTransactionError ile reddedildi.
- Vite production build ve Ruff başarılı.
