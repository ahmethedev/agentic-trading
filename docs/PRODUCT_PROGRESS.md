# ThatsMyQuant — ilk ürün dilimi

12 Eylül 2026. PRODUCT.md §10'un ilk üç adımını başlatan yerel uygulama teslimi.
Bu rapor bütün ürün yönünün tamamlandığı anlamına gelmez.

## Çalışan akış

- Mevcut React/Vite ve FastAPI üzerinde açık tema, yerel IBM Plex fontları,
  responsive navigasyon, fiyat/hacim grafiği, strateji kuralları ve karar günlüğü.
- Anahtarsız piyasa keşfi; hesap kayıtları için ayrı operatör erişim kodu.
- Hazır sorular ve desteklenen serbest metin aynı sunucu sorgu yönlendiricisine gider.
  Yanıt gerçek SQL sonucundan üretilir. **LLM henüz bağlı değildir**; bu durum UI'da görünür.
- Her yanıt sorgu adı, zaman, süre ve varsa run referansı taşır.
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
3. LLM/harness bağlantısı ve PostgreSQL sohbet/araç çağrısı geçmişi.
4. Kalıcı ATK çağrı izi, model/config sürümü ve bütün demo senaryoları.
5. Mevcut canlı çıkış yönetimi/mutabakat eksiklerinin execution kabul kapılarıyla
   tamamlanması. İlk ürün dilimi bu eksikleri çözmüş gibi göstermez.

Deneyler ekranı henüz durum açıklamasıdır; taslak/gölge çalıştırma düğmesi veya
uydurulmuş simülasyon sonucu yoktur. Sohbet sayfa oturumunda tutulur ve sayfa
yenilenince kaybolur. Sorgu yönlendiricisi genel doğal dil anlama iddiası taşımaz.

## Doğrulama

- İzole yerel PostgreSQL üzerinde 97 test geçti; prod test yazımı yapılmadı.
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
