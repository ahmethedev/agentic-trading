# Agentic Trading Hackathon — uygulama ajanına başlangıç dosyası

Hazırlanma: 11 Eylül 2026 · Etkinlik: 12 Eylül 2026 · Saat dilimi: Europe/Istanbul

Son yönlendirme: Kullanıcı kendi R sistemini deneyim aktarımı olarak anlattı; ajanın bunu değişmez veya kârlılığı kanıtlanmış strateji sanmasını istemiyor. %1 risk, %2 üst sınır, %30/%60/%10 çıkış ve gerçek girişe stop yaklaşımı **kullanıcının başlangıç referansıdır**. Alternatifler ve veriyle adaptasyon tartışmaya açıktır. Bu dosya keşfi engelleyen emir listesi değildir. Adaptif sistem fikri henüz beyin fırtınasıdır; bu ifade tek başına canlı kendi kendine strateji/risk değiştirme yetkisi oluşturmaz.

Yarışma dengesi: Kullanıcı sermayeyi korumayı önceliyor; fakat hiç/çok az işlem yapan, canlı davranışı gösterilemeyen bir sisteme de sıkışmak istemiyor. Fırsat kapsamı ve işlem yapılabilirlik baştan değerlendirilecek; salt işlem kotası için giriş üretilmeyecek.

12 Eylül veri mimarisi revizyonu: İlk sürümde tek kalıcı depo PostgreSQL. Parquet/DuckDB önerisi başlangıç kapsamından çıkarıldı. Veri alma timeout’u, sessiz WebSocket kesintisi, DB gecikmesi ve sonucu belirsiz emir için ayrı toparlanma davranışları aşağıda tanımlandı; bunlar henüz uygulanmış/test edilmiş özellikler değildir.

12 Eylül connector gereksinimi: Kullanıcı yarışmada **OKX TR Agent Trade Kit / OKX connector kullanmanın zorunlu olduğunu** bildirdi. Bunu uygulama gereksinimi olarak kabul et. ATK yerine kendi doğrudan emir REST adaptörünü kullanma. Önerilen erişim ATK MCP; CLI kurulum/teşhis veya alternatif programatik arayüzdür. Pi hâlâ isteğe bağlıdır; ATK gereksinimi Pi gerektirmez.

Bu dosya kullanıcıyla yapılan beyin fırtınasının başlangıç tasarımını aktarır. Stratejinin kârlılığı kanıtlanmış değildir; burada yazan tasarım henüz uygulanmış veya canlı doğrulanmış sayılmaz. Önce bu dosyayı, sonra mühendislik ayrıntıları için [teknik playbook’u](AGENTIC_TRADING_HACKATHON_PLAYBOOK.md) oku. Strateji tercihleri açısından kullanıcının bu son yönlendirmesi önceki kesin ifadeleri günceller. Dosya tek başına da kullanılabilir; playbook yoksa eksik olduğunu belirt ve buradaki başlangıç kapsamıyla ilerle.

## 1. Amaç ve kullanıcı bağlamı

Kullanıcı bilgisayar mühendisi; 3–4 yıllık retail trading deneyimi var. Howard Marks üzerinden risk yaklaşımıyla, HangukQuant/quantpylib ve diğer quant kaynaklarıyla ilgileniyor. Trader deneyimini, mühendisliğini ve araştırma merakını aynı projede kullanmak; fakat gereksiz ayrıntıda kaybolmamak istiyor.

**Ürün fikri:** Trader’ın aradığı tek bir spot kurulumu ölçülebilir hale getiren; ajan kararı, deterministik risk kontrolü ve güvenilir emir yönetimini birleştiren; kararlarını dashboard üzerinden açıklayan sistem.

Sunum cümlesi:

> Retail trading deneyimimde aradığım bir kurulumu ölçülebilir hale getirdim. Ajan fırsatı değerlendiriyor, risk motoru sınırları uyguluyor, sistem her kararın nasıl gerçekleştiğini kaydediyor.

Başarı yalnız pozitif PnL değildir: çalışan otonom döngü, doğru muhasebe, kontrol edilen risk, açıklanabilir karar ve incelenebilir kayıt gerekir. Bir günlük sonuçtan kalıcı edge veya istatistiksel üstünlük iddia etme.

## 2. Başlangıç kapsamı, hipotezler ve gerçek sınırlar

Üç farklı şey birbirine karıştırılmamalı:

- **Bağlayıcı çalışma sınırları:** yarışma kuralları, yetkili hesap, geçerli canlı risk bütçesi, gerçek fill muhasebesi, envanter/bakiye doğruluğu ve güvenilir emir yönetimi. Öğrenme bunları devre dışı bırakamaz.
- **Test edilebilir strateji hipotezleri:** kurulum, indikatörler, zaman ölçekleri, +1R başabaş, 2,5R hedef, parçalı çıkış yüzdeleri, runner ve risk tahsis yöntemi. Ajan gerekçeyle sorgulayabilir ve alternatif geliştirebilir.
- **Teslimi kolaylaştıran mühendislik tercihleri:** Python/PostgreSQL, tek canlı stratejiyle başlama, küçük evren ve tek dashboard. Daha basit veya açıkça daha uygun bir çözüm varsa gerekçeyle uyarlanabilir; her rutin değişiklik için izin istemek gerekmez.

Bir risk tercihinin araştırılabilir olması, çalışan sistemde limitin kendiliğinden kaldırılabileceği anlamına gelmez. Mevcut referansın %2 üst sınırını geçici operasyonel tavan olarak koru; farklı canlı risk alanı kullanıcıyla netleştirilir. Strateji üzerinde düşünmeyi bu sayıya kilitleme.

| Alan | Başlangıç önerisi |
|---|---|
| Piyasa | Yarışmanın izin verdiği OKX TR spot; long veya nakit |
| Strateji | Yükseliş bağlamında geri çekilme sonrası önceden belirli seviyenin geri kazanılması |
| Teyit | Göreli hacim ve gerçekleşmiş agresif alış/satış akışı |
| Frekans | Gün içi, seçici işlem; hızlı piyasa verisi, daha seyrek işlem niyeti |
| Başlangıç evreni | Entegrasyon önce tek uygun paritede; çalışınca aynı kurulumu birkaç izinli ve likit paritede tara. 3–5 parite uygulama önerisidir, zorunlu sayı değildir |
| Eşzamanlı pozisyon | İlk sürümde en fazla bir; bekleyen giriş de bütçeye dahil |
| Risk | Varsayılan işlem bütçesi %1, azami %2; anlamlı stop; +1R’da stop gerçek girişe, +2R’da %30 satış, +2,5R’da %60 satış, %10 runner |
| Ajan | Araçlardan bağlam toplayıp izinli niyet veya WAIT seçer; risk tavanını değiştiremez |
| Dashboard | İlk geliştirme aşamasından itibaren, tek sayfa |
| Veri | Karar/emir/fill kayıtları ve seçili paritelerin ham piyasa akışı saklanır |

İlk gün öncelik verilmeyen işler: HFT/latency arbitrage, market making, Rust/C++ yeniden yazımı, ikinci borsa, ClickHouse/Kafka/Redis altyapısı, geniş strateji optimizasyonu, canlı kodunu sınırsız değiştiren ajan, kapsamlı auth/üyelik/ödeme sistemi. Küçük bir gölge karşılaştırma ve sınırları belli bağlamsal adaptasyon tasarımı kapsamla uyumludur; öğrenme altyapısı yeni bir büyük projeye dönüşmemeli.

Range alımı ve reversal stratejisi başlangıçta ikinci aşama önerisidir. Veri/kurallar ilk hipotezi uygun göstermiyorsa ajan daha uygun bir başlangıç stratejisi önerebilir; birden çok canlı stratejiyi aynı gün yetiştirmek zorunda değildir. RSI divergence, funding ve OI erişimi kolaysa gözlem verisi olabilir. Ek veri bağlantısı teslimi geciktirecekse ertele.

**Kapsam filtresi:** Yeni özellik yarın verilecek bir kararı, riski veya sonucu açıklama biçimini somut olarak iyileştirmiyorsa araştırma listesine koy. Kullanıcıya her rutin teknik seçim için yeniden soru sorma; başlangıç önerilerini kullan, önemli strateji değişikliğinin gerekçesini ve durumunu görünür kıl.

### Sermayeyi koruma ve yarışmada fırsat bulma dengesi

“Para kaybetmemek” kullanıcının önceliğidir; işlem yaparken sıfır zarar garantisi verilemez. Bunu sınırlı zarar bütçesi, maliyeti karşılayabilecek kurulum ve gereksiz işlemden kaçınma olarak uygula. Hedef, tanımlı risk sınırları içinde yeterli canlı gözlem ve nitelikli işlem fırsatı bulmaktır. İşlem adedini tek başına başarı veya ajanın optimize ettiği ödül yapma.

Fırsat yaratmak için önce kapsamı ve çalışma süresini iyileştir:

1. Tek parite entegrasyonu çalışınca aynı kurulumu birkaç izinli, spread/derinliği uygun paritede tara. Aynı anda tek pozisyon ve aynı toplam risk bütçesi korunur; birbiriyle korelasyonlu çok sayıda aday bağımsız fırsat kanıtı değildir.
2. Gereksiz özellik geliştirmeyi kısaltıp kabul kapıları geçildiğinde canlı gözlem süresini artır. Geç kaldık diye gün sonunda büyük risk alma.
3. Canlı öncesi mevcut tarihsel mum/fixture ve gölge gözlemde kurulumun oluşma sıklığına bak. Geçmiş order flow yoksa tam teyitli stratejinin sıklığını ölçmüş gibi davranma. Amaç işlem kotası tutturmak veya geçmiş kârı optimize etmek değil, yanlış birim/pencere/aşırı dar tanım nedeniyle sistemin hiç aday üretemediğini erken fark etmektir.
4. Fiyat, hacim ve flow dışındaki ilave indikatörleri gerekçesiz zorunlu koşula dönüştürme. Yapısal stop ve maliyet/risk doğruluğu korunur. 2,5R başlangıç hipotezidir: örneğin daha yakın hedefin maliyet sonrası beklentisi farklı bir modelde araştırılabilir; yalnız işlem sayısı artsın diye aktif plan sessizce değiştirilmez.

**Gölge çalışmada aday akışı:** izlenen pariteler → uygun rejim → fiyat kurulumu → hacim/flow teyidi → maliyet/risk kabulü → ajan niyeti → emir → gerçek fill. Her aşamada sayı, oran ve geçen süre göster. Aynı kurulumun ardışık mumlarda tekrar gözlenmesini yeni bağımsız fırsat diye şişirme; episode/candidate kimliği kullan.

İşlem gelmiyorsa şu ayrımı yap:

| Gözlem | Eylem |
|---|---|
| Veri/warm-up geçersiz, scanner hiç çalışmıyor | Teknik sorunu düzelt; yokluğu piyasa görüşü sayma |
| Rejim uygun ama kurulum oluşmuyor | Seviye/pencere hesabını incele; fırsat yoksa bekle |
| Çok sayıda kurulum tek teyitte eleniyor | Birim/veri hatasını araştır, sınırda kalan değerleri göster; yalnız adet artsın diye eşiği düşürme |
| Risk/maliyet nedeniyle eleniyor | Ret gerekçesini koru; uygun başka pariteyi değerlendir |
| Niyet var fakat emirler dolmuyor | Fiyat sınırı, ret, TTL ve fill davranışını incele; otomatik sınırsız taker fallback yapma |
| Günün çoğunda veri/karar sistemi kapalı kalmış | Az işlemi seçicilik başarısı gibi sunma; çalışma süresini raporla |

Örneğin 60 dakika yeni uygun aday yoksa bir tanılama raporu üretilebilir; bu süre başlangıç önerisidir ve otomatik emir, risk artışı veya strateji değişimi tetiklemez. Fırsat az diye başka bir stratejiyi son anda canlıya ekleme. Uygun kurulum varsa işlem yap; yoksa WAIT ve gerekçesi görünür kalır.

Günlük zarar bütçesi, giriş riski ve işlem sayısı ayrı kavramlardır. %1 başlangıç referansıdır; geçerli risk alanı içinde miktar/bütçe koşullara göre değişebilir, fakat bu seçim önceden tanımlı profil ve kaydedilmiş gerekçeye dayanır. Sadece çok işlem yapma veya kaybı geri alma isteği risk artırma nedeni değildir. Kalan günlük bütçe normal işlem riskinden küçükse küçültme/vazgeçme politikası açık olmalı; geçmiş stoplar yeni zarar bütçesi yaratmaz. Açık risk ve yeni giriş günlük sınırla birlikte değerlendirilir; sınır garantili maksimum gerçekleşen kayıp değildir.

Runner da fırsat maliyeti yaratır: %10 pozisyon açıkken tek pozisyon kuralı yeni girişi engelleyebilir. Dashboard bunu ayrı ret nedeni gösterir. Bu gerilimi çözmek için runner’ı görünmez yapma veya ikinci pozisyonu sessizce açma; runner çıkış politikası netleştirilirken bu tercih kullanıcıya belirtilir.

Sunum için zorunlu canlı işlem kotası uydurma. Kamuya açık değerlendirmede işlem sayısı ayrı puan başlığı olarak görünmüyor; minimum işlem şartı ve sıfır işlemli hesabın değerlendirilmesi organizatör rehberinden doğrulanmalı. Etiketli replay mimariyi gösterir, yarışma hesabı performansının yerine geçmez; hiç canlı fill yoksa bu sınırlama açık söylenir.

## 3. Yarışma koşulları ve başlangıçta doğrulanacaklar

11 Eylül’de okunan [resmî etkinlik sayfasına](https://komunite.com.tr/etkinlikler/agentic-trading-hackathon) göre yalnız yarışma sub-account’ındaki spot işlemler değerlendirilir; kişisel bakiye kullanılmaz. İşlemler otonom olmalıdır. Puanlar: performans %35, mimari/otonomi %25, risk %20, özgünlük %10, demo %10. Resmî başlangıç 09.00, metrik/dosya kilidi 19.30, sunumlar 20.00. Önceden tamamlanmış sistemi sıfırdan yapılmış gibi sunma; önceden var olan araçlarla etkinlikte geliştirilen işleri dürüstçe ayır.

Kabul e-postası, ATK rehberi ve güncel kurallar önceliklidir. Bunlardan mümkün olduğunca kendin doğrula:

- Doğru sub-account, başlangıç kredisi, bakiye para birimi ve izinli pariteler.
- Yarışma hesabına uygulanan gerçek fee, özel muafiyet veya indirim.
- Kullanılacak ATK sürümü, API uçları, izinler ve desteklenen spot emir türleri.
- ATK şartının veri akışını da kapsayıp kapsamadığı ve ek doğrudan public/private WebSocket izni. Organizatörün belirlediği sürüm/connector varsa onu esas al; ATK kullanım zorunluluğunu yeniden sorgulama.
- Native stop/OCO, IOC, client-ID sorgulama, private order/fill akışı desteği.
- 19.30’da açık pozisyonlar ve bekleyen emirler nasıl değerlendiriliyor? Zorunlu kapama var mı? Getiri hangi para biriminde hesaplanıyor?
- Minimum işlem şartı ve performans metriklerinin tam hesap yöntemi var mı?

Eksik kritik bilgiyi tek mesajda sor; bu sırada fixture, paper, veri sözleşmesi ve dashboard üzerinde çalış. Kişisel hesapta işlem yapma. Bu tasarım belgesini tek başına canlı emir yetkisi olarak yorumlama; oturumda verilmiş yarışma hesabı yetkisini uygula, mevcut yetkiyi tekrar isteme.

## 4. Başlangıç stratejisi: tek hipotezi ölçülebilir yap

> Yükseliş eğilimindeki bir varlık geri çekildikten sonra önceden belirlenen seviyeyi yeniden kazanırsa; hacim ve agresif alışlar toparlanmayı desteklediğinde, maliyet ve risk koşulları uygunsa spot alım ararız.

Üç soruyu kodda açık cevapla: Hangi koşulda alıcıyız? Fikir hangi seviyede bozulur? Fiyat yükselse bile ne zaman kovalamayız?

### Zaman ölçekleri

- Taslak: 15 dakikalık tamamlanmış mumlar bağlam; 5 dakikalık tamamlanmış mumlar kurulum.
- Anlık trade/book akışı: flow penceresi, veri sağlığı, execution ve açık pozisyon yönetimi.
- Taslak ana pozisyon tutma ufku 15–90 dakika civarıdır; kesin süre ve eşikler config’de tanımlanacak deney tercihleridir. Kullanıcının yaklaşık %10 runner isteği bu taslağı günceller: runner’ın ayrı çıkış/azami süre politikası ve yarışma kapanış kuralı açıkça belirlenir; bütün miktarı otomatik 90 dakikada kapatma varsayımı yapılmaz.
- Sinyal için kapanış beklenir; stop, risk azaltma veya fill işlemek için mum kapanışı beklenmez.
- Göstergeleri yeterli geçmişle ısıt; order-flow penceresi dolmadan teyit üretme. OKX’te tamamlanmış mum alanını (`confirm`) doğrula.

### Rejim ve fiyat yapısı

İlk sürümde basit, denetlenebilir trend bağlamı yeterli: örneğin fiyatın referans ortalamaya göre konumu ve normalize edilmiş eğimi. Düşük trend gücünü otomatik range sayma. Reversal, ayrı bir sürekli rejimden çok geçiş olayı olabilir.

Yükseliş bağlamında kurulum ara; düşüş, range, çelişki veya geçişte WAIT geçerli davranıştır. Rejim değişiminde birkaç kapanışla teyit ve farklı giriş/çıkış eşikleri düşünülebilir; bunlar stop’u geciktiremez. BTC bağlamı varsa işlem paritesinin kendi yapısının yerine geçmez.

Giriş seviyesi sinyalden **önce** belirlenir. Örneğin geçmiş tamamlanmış mumlarla tanımlanmış seviye, altına sarkma ve üzerinde kapanışla geri kazanılabilir. Pencere ve geçersizlik koşulunu açıklaştır; seviye oluşumunu gelecekteki veriden seçme.

Price action’ın ölçülebilir karşılıkları:

- Kapanış konumu: `(close - low) / (high - low)`; sıfır aralık ayrı işlenir.
- Göreli hacim: `tamamlanan mumun quote hacmi / önceki 20 tamamlanmış mumun medyan quote hacmi`; mevcut mum paydaya girmez, sıfır/eksik payda ayrı durumdur.
- Uzama: referans seviyeye uzaklığın ATR ile normalizasyonu; aşırı uzak giriş reddedilir.
- Geçersizlik: kurulumun bozulduğu önceden tanımlanmış seviye.

Pivot sağındaki mumlarla onaylanıyorsa ancak onay geldiğinde kullanılabilir. EMA, RSI ve fiyat yapısını bağımsız üç kanıt gibi sayma. Bu dosyada optimum indikatör/eşik seçildiği iddia edilmiyor: küçük bir config belirle, varsayım olarak kaydet ve gün içindeki birkaç sonuca göre sürekli değiştirme.

### Order flow

İlk teyit gerçekleşmiş public trade akışından üretilir. Book, öncelikle spread/derinlik ve miktara bağlı maliyet kontrolü içindir; büyük bekleyen emir tek başına alım sinyali değildir.

```text
B = son 60 saniyedeki taker-buy işlemlerinin quote notional toplamı
S = son 60 saniyedeki taker-sell işlemlerinin quote notional toplamı
flow_imbalance = (B - S) / (B + S)
```

60 saniye başlangıç taslağıdır. Taker yönünü venue sözleşmesinden doğrula. Toplam hacim düşük, pencere eksik veya bağlantı kopuksa güvenilir teyit yoktur; eksik akışı nötr/sıfır sayma. Pozitif delta tek başına yükseliş garantisi değildir; fiyatın seviye kazanımıyla birlikte yorumlanır. Veri yalnız kaynak borsa/pariteyi temsil eder. Anlık flow, tutma ufkunun tamamını tahmin ettiği iddiasıyla kullanılmaz.

### Funding ve RSI

Kaldıraçsız spotta funding gideri yoktur. Perpetual funding/OI yalnız dış bağlam olabilir; kaynak, zaman ve periyotla kaydet, negatif funding’i otomatik spot alıma çevirme. RSI divergence pivot/onay kuralları gerektirir; önce gözlemde tut. Aynı gün birkaç örnekten yeni canlı filtre üretme.

## 5. Risk ve execution: küçültülmeyecek çekirdek

### Kullanıcının risk yaklaşımı — korunacak referans, test edilecek hipotez

Kullanıcı için en önemli bileşen risk yönetimi. Tek işlemin sonucundan çok sürecin toplamına bakıyor; 2–3 ardışık stop stratejiyi anında değiştirme nedeni değil. Kendi risk/ödül yapısının kârlı olmayabileceğini veya gereğinden korumacı olabileceğini açıkça kabul ediyor. Aşağıdaki plan `retail_baseline_v1` olarak korunur; ajanın bütün stratejilere zorunlu uygulayacağı yasa değildir. Alternatifler bununla karşılaştırılır; **gerçekleşen net R dağılımı** ve fırsat maliyeti ölçülür.

| Aşama | Kullanıcının belirttiği davranış |
|---|---|
| Başlangıç riski | İşlem başına bakiyenin %1’i; en fazla %2 |
| R yaklaşımı | Hesap açısından 1R yaklaşık bakiyenin %1’i |
| İlk stop | İşlem fikrini bozan anlamlı fiyat seviyesi; miktar bu seviyeye göre hesaplanır |
| Ana hedef | Girişte en az 2,5R alan aranır; seçilen çıkış planında +2,5R’da ilk miktarın %60’ı satılır |
| Fiyat +1R’a geldiğinde | Stop gerçek ortalama giriş fiyatına taşınır; maliyet eklenmez |
| Fiyat +2R’a geldiğinde | İlk gerçekleşen pozisyon miktarının %30’u satılır |
| Runner | İlk gerçekleşen pozisyonun %10’u sürpriz yükselişler için açık kalır |
| Kayıp serisi | Sırf 2–3 stop oldu diye risk artırılmaz veya strateji değiştirilmez; tanımlanmış günlük risk sınırı ayrıca geçerlidir |

Referans profilde %1 varsayılanını kullan; %2 önceki kullanıcı bilgisinden gelen geçici üst sınırdır. Kullanıcı adaptasyonu tartışmaya açtı, fakat risk artırmanın sayısal koşulları henüz seçilmedi. Geçerli çalışma alanı tanımlandıktan sonra ajan izinli profiller arasında seçim yapabilir; LLM’nin kendi beyan ettiği güven yüzdesi risk artırmak için yeterli kanıt değildir. Günlük zarar/portföy bütçesi henüz belirlenmedi; işlem başına %1 sınırını günlük %1 sınırı gibi yorumlama. Runner açık pozisyondur; tek pozisyonlu başlangıç mimarisinde bu sınırı tüketir.

### R tanımı ve spot miktar hesabı

Hesap riski ile fiyatın stop mesafesi cinsinden ilerlemesini karıştırma. İsimleri açık tut:

```text
equity_at_decision = karar anındaki, yarışma para birimine çevrilmiş net hesap değeri
account_r_unit    = equity_at_decision × 0.01
risk_budget       = equity_at_decision × risk_fraction  # varsayılan 0.01; üst sınır 0.02
price_r_distance  = entry_reference - initial_structural_stop  # spot long; pozitif olmalı
quantity_candidate = risk_budget / (price_r_distance + estimated_cost_per_unit)
quantity          = bakiye, fee rezervi, likidite, lot ve venue limitleriyle sınırlanan miktar
```

Maliyet miktara bağlıysa book-walk ile yeniden değerlendir. Canlı uygulamada equity tabanı ve ücret değerlemesini açık config/muhasebe sözleşmesiyle sabitle. Kullanıcının %2 bütçe kullandığı işlem hesap ölçeğinde 2 birim risk taşır; bunu sessizce hesap ölçeğinde 1R diye raporlama.

Fiyat tetikleri için başlangıç stop mesafesi referans alınır: giriş +1×, +2× ve en az +2,5× mesafe. Gerçek fill sonrası ağırlıklı giriş ve değişmeyen yapısal stop ile geçerli seviyeleri hesapla, bütçeyi tekrar kontrol et. Giriş emri sonuçlandıktan sonra ilk miktar, ilk stop, fiyat-R mesafesi ve tahmini maliyet dahil başlangıç riski dondurulur. Kısmi fill süresince mevcut envanter hemen korunur; çıkış tetiklenirse bekleyen giriş önce iptal/mutabakat sürecine alınır, miktar sınırsız değişmez.

Stop başabaşa taşındı veya kâr alındı diye başlangıç R paydasını küçültme. Ledger/dashboard ayrı gösterir: fiyatın stop mesafesi cinsinden ilerlemesi, gerçek net PnL / dondurulmuş başlangıç risk tutarı, hesap getirisi ve hesap-R birimi. Bütçe/likidite nedeniyle daha küçük açılan işlemi yine %1 risk alınmış gibi raporlama.

**Spot sınırı örneği, maliyetler hariç:** 1.000 birim hesapta 10 birim risk bütçesi ve %0,5 stop mesafesi 2.000 birim notional gerektirir. Kaldıraçsız spot bakiye buna yetmez; miktarı azalt, risk bütçesinin tamamını kullanmak için stop’u anlamsız biçimde genişletme veya borçlanma. %2 stopta aynı 10 birim risk 500 birim notional ile elde edilir. Hedeflenen risk bir tavan/bütçedir; mutlaka harcanacak miktar değildir.

### Kademeli çıkışlar ve runner

- Referans profilde en az 2,5R hedef yalnız aritmetik bir fiyat etiketi olmasın: görünür fiyat yapısı, oynaklık, maliyet ve kalan yarışma süresi açısından makul alan aranır. Kuruluma uydurmak için stop daraltılmaz. Alternatif hedefler ayrı profil/deney olarak değerlendirilebilir.
- Referans profilde +1R’da stop **gerçek ağırlıklı ortalama giriş fiyatına** taşınır. Kullanıcının anlattığı davranışı bu profilde doğru uygula; net başabaş veya gecikmiş trailing denemesi ayrı sürüm olur. Girişe stop brüt fiyat başabaşıdır: komisyon ve kayma nedeniyle net zarar olabilir. Stop tetik seviyesi gerçekleşecek fill fiyatını garanti etmez.
- Referans plan: +2R’da ilk gerçekleşen miktarın %30’u, +2,5R’da %60’ı satılır; %10 runner kalır. +2R satışı sonrası kalan miktarın %60’ını satmak bu plan değildir. Kullanıcının anlattığı planı yeniden sormak gerekmez; bunun en iyi plan olduğunu varsaymak da gerekmez.
- Yüzdeler kalan miktar yerine ilk gerçekleşen base miktara göre tanımlanır. Fee ve lot yuvarlaması sonrasında satılabilir miktarı aşma; her kâr alma aşaması bir kez uygulanır. Kısmi TP fill’lerinde aşamanın hedef miktarı tamamlanmadan tamamlandı sayılmaz.
- Runner’ın yaklaşık %10 miktarı emir minimumunu karşılamıyorsa bunu anlamlı bir açık pozisyon gibi gösterme. Birleştirme/dust politikası belirle; asgari emri tutturmak için toplam riski artırma.
- Runner için trailing yöntemi/mesafesi ve azami süre henüz seçilmedi. İlk stop→başabaş davranışı geriye alınmaz; runner yarışma kapanış/koruma kurallarından muaf değildir. Native TP/stop ile envanter kilitleme/OCO davranışını venue üzerinde doğrula.

**Hedef R ile gerçekleşen R farklıdır.** Seçilmiş planda %30 miktar +2R, %60 miktar +2,5R, %10 miktar girişte kapanırsa brüt toplam `0.30×2 + 0.60×2.5 + 0.10×0 = 2.1R` olur. Bu, başlangıç miktarı × ilk fiyat-stop mesafesi biriminde ve maliyetler hariç hesaptır. Runner +5R’da kapanırsa aynı toplam +2,6R; yalnız ilk %30 satış gerçekleşip kalan %70 girişte kapanırsa +0,6R olur. Gerçek fill, fee ve başlangıç risk paydasına göre net sonuç ayrıca hesaplanır. Runner kazancı bilinmeden tüm pozisyonun +2,5R kazanacağını varsayma.

Risk/ödül hedefi tek başına pozitif beklenti sağlamaz. Tam kayıplar, başabaş görünen maliyetli çıkışlar, parçalı kazançlar ve runner sonuçları birlikte ölçülür. Basit ikili modelde +2,5R kazanç / −1R kayıp için maliyet öncesi başabaş kazanma oranı yaklaşık %28,6’dır; bu parçalı çıkış stratejisine doğrudan uygulanmaz. +1R’da başabaşa geçişin, daha sonra hedefe gidecek işlemleri erken kapatma ihtimalini de kaydet.

### Uygulama kuralları

- Trade başına risk, toplam açık/bekleyen risk, notional ve günlük zarar sınırını ayrı config alanları yap. İşlem riski tercihi yukarıda verildi; hâlâ açık olan günlük bütçe ve çıkış ayrıntılarını kesinleşmiş gibi uydurma.
- Miktarı stop mesafesi ve maliyet tamponuyla hesapla; kullanılabilir quote bakiye, likidite ve venue limitleriyle sınırla. Minimum miktara ulaşmak için risk bütçesini aşma.
- Bekleyen emirler de bütçe tüketir. İptal isteği göndermek rezervasyonu serbest bırakmaz.
- İlk stop kurulumun bozulduğu seviyeye dayanır. Fill sonrası maliyet ve risk yeniden hesaplanır; kötü dolumu gizlemek için stop’u otomatik genişletme.
- Stop, süre/ilerlememe çıkışı ve basit trailing birbirleriyle tutarlı olsun. Ortalama düşürme, martingale ve zarar sonrası risk artırma yok.
- Günlük zarar sınırının gerçekleşmiş + açık PnL, fee ve referans equity ile nasıl hesaplandığını tanımla. Limitte yeni giriş durur; açık pozisyon yönetimi sürer. Stop kaybı garantili üst sınır değildir.
- Fee’yi hesap/enstrümandan al; eski repo sabitlerini taşıma. Fee para birimi, maker/taker, rebate ve satılabilir envanteri doğru kaydet.
- Tahmini gidiş-dönüş maliyeti giriş filtresidir; hedefin maliyeti aşması tek başına pozitif beklenti kanıtı değildir.
- Gerçek net PnL gerçek fill fiyatlarından ve fee’lerden hesaplanır; fill içine yansımış spread/slippage ikinci kez düşülmez.

İlk emir politikası, hesapta destekleniyorsa fiyat sınırı olan marketable limit/IOC olabilir. Fill garantisi yoktur; kısmi miktar kabulü veya vazgeçme açık politikadır. Pasif limit, TTL ve sınırlı reprice daha sonra eklenebilir. Limit emir otomatik maker değildir. Normal giriş maliyet sınırı ve acil risk azaltma politikası ayrı tanımlanır.

Asgari emir davranışı:

1. Gönderimden önce kalıcı intent + risk/bakiye rezervasyonu.
2. Timeout → UNKNOWN → borsadan sorgulama/mutabakat. Kör yeniden gönderim yok; client-ID tek başına sonsuz idempotency garantisi sayılmaz.
3. Fill ACK’den önce gelebilir; geç ACK terminal durumu geriye çeviremez. Aynı fill iki kez işlenmez.
4. Kısmi fill hemen envantere ve korumaya yansır. Cancel sırasında ek fill olabilir; kalan miktar uzlaşmadan replacement gönderilmez.
5. Spot satış miktarı gerçekten sahip olunan ve kullanılabilir base miktarla sınırlıdır; perpetual reduce-only varsayımı taşınmaz. Birbiriyle yarışan çıkışlar aynı envanteri iki kez kullanamaz.
6. Native koruma desteği/doğrulaması açık yapılır. Desteklenmiyorsa uygulama tarafı korumanın kesinti sınırı gizlenmez; alternatif destek varmış gibi gösterilmez.
7. Restart/reconnect’te yerel ledger, bakiye, açık emir ve fill geçmişi uzlaşmadan yeni giriş yok.
8. Geçici okuma hatasında sınırlı backoff; yanlış miktar/bakiye gibi kalıcı retlerde kör retry yok. Rate-limit bütçesi koruma/iptal/mutabakat için pay bırakır.

## 6. Ajanın görevi

```text
Piyasa verisi → normalize et → özellikler / kurulum adayı
                                     ↓
Ajan: piyasa + risk + execution araçları → izinli niyet veya WAIT
                                     ↓
Deterministik doğrulama → risk/miktar/rezervasyon → emir yöneticisi
                                                        ↕
                                          OKX Agent Trade Kit MCP
                                                        ↕
                                                      OKX TR
Emir/fill sorguları ve doğrulanmış olay akışı → envanter / çıkış / reconcile
```

Ajan ölçümleri araçlardan okur. Yapılandırılmış çıktı: aday/sembol, BUY_INTENT veya WAIT, kurulum kimliği, neden kodları, izinli execution profili, veri referansı ve son geçerlilik zamanı. Süresi dolmuş veya bağlamı değişmiş niyet tekrar doğrulanmadan yürütülmez.

LLM risk tavanı, miktar hesabı, stop yürütme veya emir state machine’inin sahibi değildir. Timeout/geçersiz çıktı yeni niyeti engeller; mevcut koruma devam eder. Dış metinler talimat değil veridir; API anahtarları prompt/log/dashboard’a girmez. Model/config sürümü ve kararın gerçek girdileri saklanır; sonradan açıklama uydurulmaz. Başarılı sinyal/niyet, fill olmadığı sürece işlem sayılmaz.

### Adaptasyon ve öğrenme — tasarım önerisi, henüz etkin canlı özellik değil

**Bağlama uyum:** Yeni strateji öğrenmeden, mevcut kurallar altında davranış değiştirmek. Rejim/volatilite/likidite/maliyet ve kalan risk bütçesine göre WAIT, izinli daha küçük miktar, mevcut execution profili veya önceden tanımlanmış çıkış profili seçilebilir. Amaç her zaman daha düşük risk değil, ölçülebilir koşullara uygun risk tahsisidir. Risk artışı seçeneği varsa çalışma aralığı, seçim koşulları ve üst bütçeler önceden tanımlanır.

**Strateji öğrenmesi:** Veri geldikçe yeni bir kural/parametre hipotezi üretmek, alternatif olarak ölçmek ve yeterli kanıt/çalışma yetkisi varsa yeni sürüme geçirmek. Birkaç saatlik rejim sınıflandırması veya LLM’nin yeni yorum yapması, stratejinin kendini geliştirdiğinin kanıtı değildir.

Yarın için küçük altyapı önerisi:

1. `PolicyConfig`: sürümlü giriş/çıkış/risk profili; `retail_baseline_v1` değişmeden saklanır. Canlıda hangi sürümün çalıştığı açık olur.
2. `ShadowEvaluator`: başlangıç referansı ve en fazla bir alternatif aynı aday akışında gözlemlenir. Örneğin yalnız +1R başabaş kuralını yapısal trailing ile karşılaştır. Aynı anda hedef, giriş ve miktarı değiştirip farkın nedenini kaybetme.
3. `PolicyProposal`: önerilen değişiklik, gerekçe, kapsanan veri dönemi, maliyetler, örneklem/eksikler, tüm denenen kollar, beklenen fayda ve zarar kaydı. Yeni kod üretimi zorunlu değil; config farkı yeterli.
4. `PromotionGate`: öneri → gölge değerlendirme → ayrı ileri dönem kontrolü → geçerli yetki/risk alanı içinde aktivasyon → izleme/geri dönüş. Terfi şartları henüz seçilmedi; varsayılan yeni öğrenilmiş kuralın otomatik canlıya alınmamasıdır. İzinli profiller arasında mevcut bağlama göre seçim bununla karıştırılmaz.

Gölge PnL gerçekleşmiş PnL değildir; kuyruk/dolum belirsizliği ve maliyetleriyle etiketlenir. Sonuç ufku dolmamış adaylar eğitim/terfi değerlendirmesine sıfır veya tamamlanmış sonuç olarak girmez. Aynı episode ve örtüşen pozisyonlar bağımsız örnek sayısını şişirmez. Seçim yapılan veriyi tekrar doğrulama kanıtı olarak kullanma; çok sayıda denemeden seçilmiş kazananı gizleme.

Ölçüm: net beklenti, ortalama kazanç/kayıp, drawdown ve kuyruk kayıpları, fee/turnover, fırsat sayısı ve kapladığı sermaye/süre. Tek günlük küçük örneklemde çoğu öneri sonuçsuz kalabilir; bu durumda “kanıt yetersiz” raporlanır. Sadece win rate, brüt RR, son kazanç veya LLM confidence ile terfi/risk artışı yapılmaz.

Her pozisyon açılırken profil sürümüne bağlanır. Global profil güncellemesi açık pozisyonun stopunu/TP’sini sessizce değiştirmez; izinli geçiş varsa planlı ve kaydedilmiş olur. Geri dönüş yeni girişleri önceki profile yönlendirir; dolmuş işlemleri geri almış gibi davranmaz. Adaptif bileşen bozulursa deterministik risk ve mevcut pozisyon yönetimi sürer.

Dashboard: aktif profil, bağlam nedeniyle son seçim, baseline/alternatif sonuçları, önerilen değişiklik ve kanıt durumu. İlk gün için sürümlü config + mevcut veri kaydı + tek gölge karşılaştırma yeterli olabilir. RL, online model eğitimi veya geniş optimizasyon bu konuşmanın otomatik uygulama talebi değildir; kullanıcı şu anda sesli düşünüyor.

## 7. Teknoloji ve veri mimarisi

| Katman | Tercih |
|---|---|
| Trading worker | Python + asyncio; tek aktif emir sahibi |
| Borsa erişimi | Zorunlu OKX Agent Trade Kit; Python MCP istemcisi → yerel ATK MCP süreci → OKX TR |
| ATK çalışma ortamı | Resmî Node.js/npm paketleri, yarışmaya uygun kilitlenmiş sürüm; CLI teşhis/alternatif erişim için |
| Sözleşmeler / hesap | Pydantic, para ve miktarda Decimal; feature hesaplarında uygun sayısal tipler |
| API | FastAPI |
| Dashboard | React + Vite; Lightweight Charts ve Recharts |
| İşlem/karar kayıtları | PostgreSQL, transaction + benzersizlik kısıtları |
| Piyasa verisi ve arşivi | Aynı PostgreSQL içinde ayrı mum/trade/book tabloları; toplu yazım |
| Analiz | PostgreSQL SQL sorguları; gerektiğinde Python/NumPy/pandas |

Bu teknolojilerin çoğu mevcut projede kullanılıyor; aynı bağımlılık sürümlerini körlemesine taşıma, çalıştığı doğrulanmış küçük bir ortamı kilitle. Dashboard API worker sayısı trading worker sayısını artırmamalı. Senkron DB veya ağır analiz çağrıları async emir/veri döngüsünü bloke etmemeli.

### Zorunlu OKX Agent Trade Kit bağlantısı

[Resmî ATK sayfası](https://tr.okx.com/en/agent-tradekit) MCP ve CLI erişimini sunuyor. Paketler `@okx_ai/okx-trade-mcp` ve `@okx_ai/okx-trade-cli`; güncel repo Node.js >=18 belirtiyor, seçilen sürümün engine şartını kurulumda doğrula. [Güncel yapılandırmada](https://github.com/okx/agent-trade-kit/blob/github-main/docs/configuration.md) `site = "tr"` var. Yarışma sub-account profili ve demo/live seçimi açık yapılır; global varsayımıyla başlatma. Anahtarlar sohbet veya loglara girmez. Bu oturumda araç envanterinde hazır OKX connector bulunamadı; belge incelemesi kurulum/hesap bağlantısı yapıldığı anlamına gelmez.

Önerilen uygulama: Python worker kalıcı bir stdio MCP oturumu açar, initialize/list-tools ile seçili sürümün gerçek şemalarını öğrenir. Tek uzun ömürlü süreç kullan; her tick’te yeni CLI/MCP süreci başlatma. Harness ajan araç döngüsünü yönetmeye devam eder; ATK borsa araçlarını sağlar, strateji/risk/ledger’ın yerine geçmez. MCP araçları model çağrısı gerekmeksizin deterministik koddan da çağrılabilir.

| İhtiyaç | Dokümandaki ATK araç örnekleri |
|---|---|
| Piyasa ve geçmiş veri | `market_get_candles`, `market_get_orderbook`, `market_get_trades` |
| Hesap ve ücret | `account_get_balance`, `account_get_fee_rates` |
| Emir ve mutabakat | `spot_place_order`, `spot_cancel_order`, `spot_get_order`, `spot_get_fills` |

İsim/parametre ve stop/OCO yeteneklerini kurulu sürümde doğrula; dokümanlar sürümler arasında farklılaşabilir. Ajanın okuma araçları ATK verisine ve PostgreSQL özelliklerine ulaşır. Yazma tarafı yalnız risk kontrolü, kalıcı intent ve rezervasyondan sonra emir yöneticisince çağrılır. LLM’ye risk motorunu atlayan ham trade araçları veya serbest shell yolu verme. `account` dahil açılan modüllerde araç bazlı allowlist uygula; salt modül seçimini tam risk kontrolü sanma. CLI ile MCP aynı anda bağımsız emir sahibi olmaz.

ATK’nın son işlemler/orderbook sorgusu sağlaması kesintisiz streaming, eksiksiz order flow veya private fill aboneliği sağladığını kanıtlamaz. Bu yetenekleri incele. Doğrudan WebSocket ancak yarışma kapsamı izin verirse ek veri kanalı olabilir; borsa emirleri yine ATK üzerinden gider. Yalnız polling varsa çağrı bütçesi/tekilleştirme ve gap algılama uygula; veri yetmiyorsa stratejinin flow beklentisini açıkça uyarla, tam tick akışı varmış gibi davranma.

MCP/CLI timeout’u, alttaki borsa işleminin iptal edildiği anlamına gelmez. Süreç yeniden başlatıldıktan sonra UNKNOWN emirleri ATK sorgularıyla uzlaştır. ATK’nın kendi retry/rate-limit davranışını kontrol et; dış katmanda sınırsız tekrarlarla çarpan yaratma. CLI seçilirse sabit komut+argüman listesi, doğrulanmış JSON çıktı, exit status ve sınırlandırılmış subprocess ömrü kullan; model metnini shell komutuna dönüştürme. Canlı otonomi yetkisini yarışma rehberiyle eşleştir; read-only/demo/live ayrımını ve aracın gerçek zorunlu kontrollerini koru.

İlk sürümde ek analitik depo/motor kurma. Parquet dosya biçimi, DuckDB sorgu motorudur; teknik olarak aynı şey değiller, ancak bu teslimde ikisi de gereksiz ek veri yolu yaratıyor. PostgreSQL kapasitesini veri hacmi, batch gecikmesi ve sorgu yüküyle ölç; tüm borsanın kesintisiz L2 akışını aynı rahatlıkla kaldıracağına dair ölçümsüz garanti verme. Gerekirse ileride dışa aktarım veya ClickHouse değerlendirilir. Rust/C++ yalnız ölçümle CPU/gecikme darboğazı görülen bileşenler için sonraki aşama. Her tick’te bütün geçmişi hesaplamak yerine bellekte kayan pencere/artımlı hesap kullan; HFT iddiası üretme.

### Saklanacak veriler

**PostgreSQL:** decision/feature snapshot, intent, rezervasyon, emir olayları ve güncel durum, fill, fee, envanter/pozisyon, equity, bağlantı ve mutabakat olayları. Değişiklik geçmişi kaybolmasın; güncel görünüm ile olay günlüğü birlikte tutarlı güncellensin.

**Aynı PostgreSQL içinde piyasa tabloları:** `candles`, `market_trades`, `book_snapshots` ve tam book replay seçilirse `book_deltas`. Seçili paritelerin public trades, bid/ask ve ihtiyaç duyulan derinlik verisi burada tutulur. Public trade kaydı private fill ledger yerine geçmez. Anahtar veya kimlik doğrulama başlığı arşivlenmez.

Ortak alanlar: run/session ID, venue, instrument, veri türü, exchange timestamp, received timestamp, mümkünse sequence/trade ID, şema sürümü. Yerel gecikme ölçümlerinde monotonic saat kullan; farklı makinelerin saatlerini doğrudan çıkarıp kesin tek-yön gecikme iddia etme.

Karar zinciri: `decision_id → intent_id → client_order_id → exchange_order_id → fill_id`.

Piyasa verisi yazımı bounded buffer ve ayrı async yazıcıyla küçük batch’ler halinde yapılır; her tick için ayrı commit veya LLM çağrısı yapılmaz. Batch INSERT veya yük uygunsa COPY kullanılabilir. Tekilleştirme gereken akışlarda olay kimliği ve idempotent insert/staging→merge planı gerekir; COPY kendiliğinden dedup yapmaz. Sembol+zaman sorgularına uygun az sayıda indeks kullan; bölümleme/retention ancak hacim gerektiriyorsa eklenir. Karar/emir/fee kayıtları ham veri temizliğiyle silinmez.

Tek veritabanı, tek bloklayan iş kuyruğu demek değildir: finansal kayıt işleri piyasa batch’leri ve dashboard sorgularınca aç bırakılmaz. Ayrı sınırlı bağlantı havuzları/iş kuyrukları, kısa transaction’lar ve sorgu süre sınırları kullan; aynı DB sunucusunun kaynakları yine ortak olduğu için yükü ölç. Dashboard geçmiş tick tablosunu her yenilemede baştan taramaz; mum/özetler ve sınırlı zaman pencereleri okur.

Flush ve crash davranışı tanımlanır; düşen olaylar, yazma hataları ve kuyruk gecikmesi görünür olur. RAM kuyruğu kalıcı veri değildir; yazılamayan olaylar için kayıpsızlık iddia etme. Güvenilir özellik için gerekli akış kaybında yeni giriş durur. Kritik intent/rezervasyon kaydı kalıcılaşmadan emir gönderilmez. Book replay gerekiyorsa başlangıç snapshot + delta + gap/reconnect kaydı saklanır; örneklenmiş snapshot’tan tam defter/kuyruk replay iddia edilmez.

### Timeout, bağlantı ve toparlanma sözleşmesi

Timeout beklenen işletim olayıdır; tek genel retry dekoratörüyle bütün çağrılara aynı davranışı uygulama.

| Hata / durum | Davranış |
|---|---|
| REST piyasa verisi okuması gecikiyor | Connect/read/pool ve toplam çevrim için ayrı süre sınırı. Geçici hatada sınırlı retry, exponential backoff+jitter; rate limit yanıtının bekleme bilgisini uygula. Eski cevabın yeni veriyi ezmesini önle |
| Tek parite okuması takılıyor | Parite/görev bazlı hata izolasyonu ve sınırlı eşzamanlılık; tek takılan çağrı bütün tarayıcıyı durdurmaz. Ortak bağlantı kopması etkilenen tüm paritelere yansır |
| WebSocket açık görünüyor ama akış susmuş | Venue protokolüne uygun ping/pong ve ayrı son-mesaj/son-geçerli-piyasa-verisi takibi. Pong gelmesi fiyat/book’un güncel olduğunu kanıtlamaz; trade olmaması da tek başına bağlantının bozulduğunu kanıtlamaz |
| Reconnect veya sequence boşluğu | Tek reconnect sahibi, artan bekleme ve yeniden abonelik. Book için yeni snapshot/delta senkronizasyonu; mumları REST’ten tamamlama; erişilemeyen trade aralığını gap olarak işaretleme. Flow penceresini yeterli taze veriyle yeniden ısıt |
| Veri eski/eksik | İlgili strateji girdisini geçersiz işaretle; cache yaşını koru, son fiyat var diye yeni girişe izin verme. Tazelik eşiği strateji ufkuna göre ayarlanır, bağlantı heartbeat süresiyle aynı değildir |
| Emir gönderme veya iptal timeout’u | Sonuç UNKNOWN; emrin hiç gitmediğini veya iptal olduğunu varsayma. Client/exchange ID, private olaylar ve REST emir/fill/bakiye ile uzlaştır; aynı niyeti körlemesine tekrar gönderme |
| ATK MCP/CLI süreci yanıt vermiyor veya kapandı | Yeni girişleri durdur, süreç/oturum sağlığını toparla; çağrıyı iptal etmek borsadaki emri iptal etmez. ATK üzerinden emir/fill/bakiye uzlaşmadan yazma çağrısını tekrarlama |
| DB write/commit timeout’u | İşlem başarısız veya başarılı olabilir; kimliklerle sorgula, dedup ve transaction durumunu uzlaştır. Özellikle rezervasyon/intent sonucu belirsizken yeni giriş gönderme |
| DB/piyasa yazma kuyruğu doluyor | Belleği sınırsız büyütme; lag/drop ölç, analitiği ve yeni girişleri gerektiğinde durdur. Kritik finansal kayıtların sessizce kaybolmasına izin verme |
| LLM timeout’u | Niyet üretme veya geç kalmış niyeti yürütme; mevcut risk/çıkış döngüsü bağımsız sürer |

OKX dokümanındaki uygulama seviyesinde `ping`/`pong` sözleşmesini uygula; transport ping’i aynı şey sayma. Yeniden bağlanma sonrası yalnız socket’in açılması READY olmak için yeterli değildir. Durum akışı `CONNECTING → WARMING_UP → READY → STALE/RECOVERING`; private hesap durumu belirsizse yeni girişler ayrıca bloke edilir.

Tek toplam süre bütçesi retry’ları da kapsar. Retry görevi çoğaltmasın; iptal edilmeyen senkron thread üstüne yeni thread biriktirme. Tarihsel warm-up/backfill, risk azaltma ve private mutabakat için gereken rate-limit/bağlantı payını tüketmez.

Yeni girişleri durdurmak açık pozisyonu unutmak değildir. Bağlantı varsa koruma/azaltma sürer; önceden doğrulanmış borsa tarafı stoplar uygulamadan bağımsız bekleyebilir. Tam ağ kesintisinde uygulama yeni emir veya stop güncellemesi gönderemez; bunu garanti ediyormuş gibi sunma. Toparlanma sonrası açık pozisyon, bekleyen giriş/çıkışlar ve korunan miktar uzlaşır.

Dashboard’da son geçerli veri yaşı, kanal durumu, reconnect/retry sayıları, REST gecikmesi, yazma kuyruğu boyu/yaşı, DB hatası ve son başarılı mutabakat zamanı gösterilir. Bu sözleşme kodlanıp hata enjeksiyonuyla sınanmadan “timeout yönetimi tamam” denmez.

## 8. Quantpylib yaklaşımı

Kullanıcı HangukQuant Udemy kursunu almış; quantpylib’e aşina. Erişim, yerel kurulum ve kullanım kapsamı henüz doğrulanmadı. Kütüphaneyi teslimin zorunlu bağımlılığı yapma.

İlgili fikir/modüller: trade imbalance, hareketli/üstel ağırlıklı volatilite, event journal, replay, slippage, fill sonrası markout. Dokümandaki wrapper listesinde 11 Eylül incelemesinde OKX görülmedi; hazır OKX TR entegrasyonu varsayma. Native Cython/C++ kurulum yükünü hesaba kat.

Özel repo ve paylaşım koşulları var: kurs satın alımının repo erişimi veya kodu açık teslim etme hakkı olduğunu varsayma. Çalışan ve kullanım kapsamı uygun modüller varsa küçük ölçekte yararlan; aksi halde standart yöntemleri kendi uygulamamızda kur, özel kaynak kodunu kopyalama. Kaynak gösterimi kullanım izninin yerine geçmez.

## 9. Dashboard: geliştirme aracı ve demo aynı ekran

Tek sayfanın sorusu: **Ajan ne gördü, ne karar verdi, emir ne oldu, sonuç ne?**

| Alan | İçerik |
|---|---|
| Üst durum şeridi | LIVE/PAPER/REPLAY, hesap takma adı, veri yaşı, bağlantı, kullanılan/kalan risk bütçesi, net getiri, açık pozisyon, maksimum düşüş, toplam fee |
| Grafik | Mum, hacim, önceden belirlenen seviye, gerçek giriş/çıkış fill işaretleri, stop |
| Karar kartı | BUY_CANDIDATE/WAIT, koşulların değerleri, geçen/kalan kontroller, neden kodu, karar zamanı |
| Fırsat akışı | Rejim→kurulum→teyit→risk/maliyet→niyet→emir→fill sayıları; son uygun adaydan beri süre ve birincil ret nedenleri |
| Politika / öğrenme | Aktif profil sürümü, seçimin gerekçesi; varsa baseline ve gölge alternatif, önerilen değişiklik ve kanıt durumu |
| Emir paneli | İstenen/dolan/kalan miktar, gönderim/ACK/fill, VWAP, fee, iptal/UNKNOWN durumu; ilk stop, +1R/+2R/ana hedef, başabaş ve kısmi TP durumu, runner miktarı |
| Performans/olaylar | Equity eğrisi, işlemler, ret nedenleri, hata ve mutabakat geçmişi |

Dashboard veriyi aynı kalıcı kaynaktan okur; ikinci bir PnL veya risk motoru kurma. Dashboard kapansa da bot koruması sürer. Gerçekleşmiş ve açık PnL ayrılır. Canlı/paper/replay sonuçları ayrı tutulur; gerçek zamanlı sandırılan kayıtlı demo yapılmaz. İlk sürümde dashboard’un read-only olması yeterli; kontrol düğmesi eklenirse worker’daki tek risk/emir sahibine gider.

İlk ekran emir gönderilmeden çalışsın: veri sağlığı + grafik + karar kartı + olaylar. Emir yönetimi tamamlandıkça fill ve performans panellerini ekle. İşlem çıkmayan zamanda WAIT gerekçesi anlamlı şekilde görünmeli.

## 10. Ölçüm ve sunum

- Net getiri, realized/unrealized PnL, toplam fee, açık risk ve portföy equity’sinden maksimum düşüş.
- İşlem sayısı, turnover ve piyasada kalınan süre; aynı zaman/para biriminde basit al-tut karşılaştırması.
- Canlı veri/karar sisteminin çalıştığı süre, geçerli veri oranı, benzersiz kurulum sayısı, uygun aday→niyet ve emir→fill dönüşümü. Az işlem ile teknik olarak çalışmamayı ayır; minimum işlem kotası türetme.
- Karar→gönderim, gönderim→ACK/ilk fill; istenen/dolan miktar oranı. Dolmayan emirleri rapordan çıkarma.
- Karar ve gönderim referansına göre fill VWAP farkı, maker/taker dağılımı.
- Fill sonrası 10/30/60 saniye gibi sabit ufuklarda yönü normalize markout; bu tek başına net strateji PnL değildir.
- İşlem boyunca MFE/MAE, tutma süresi, çıkış nedenleri; ölçümün veri çözünürlüğünü belirt.
- R raporu: dondurulmuş başlangıç riski, gerçek net R, hesap-R karşılığı, +1R/+2R/ana hedefe erişim, başabaş çıkışları, kademelerin ve runner’ın ayrı net katkısı. MFE/MAE’yi R cinsinden de göster; hedef RR’ı gerçekleşen ortalama kazanç/kayıp oranı sanma.
- Reddedilen adayların 5/15/30 dakika sonraki fiyat hareketi; bunu gerçekleşmiş işlem getirisi diye sunma. Henüz olgunlaşmamış veya eksik sonuç sıfır yazılmaz.
- Rejim/kurulum sayıları ve ret nedeni dağılımı; veri kesintisi ve UNKNOWN süreleri.

Baseline/flow filtreli karşılaştırma yapılırsa aynı aday akışı ve maliyet varsayımları kullanılır; paper kollar kendi emir/portföy durumunu taşır. Simüle limit dolumunu fiyata dokunma ile garanti etme. Aynı gün sonuçlarına göre kazananı seçip kanıtlanmış edge diye sunma; kısa örneklemden annualized Sharpe gibi iddiaları büyütme.

Üç dakikalık demo: problem ve kurulum → karar kartı → gerçek emir/fill zinciri → maliyet sonrası sonuç ve risk → bilinen sınırlar. Etiketli replay ile kısmi fill veya bağlantı hatası örneği gösterilebilir. Önceden var olan bileşenleri ve hackathon’da eklenen işleri ayır. Çalışır ajan, kısa README/komutlar, performans dökümü ve demo kaydı teslim edilir.

## 11. Uygulama sırası ve kabul kapıları

**Kapı 1 — Görebiliyor muyuz?** Tek paritede doğru/güncel veri, kayıt, feature hesapları ve dashboard. Mum/flow warm-up tamam, kapalı mum ve veri kalitesi kontrolleri görünür.

**Kapı 2 — Kontrol edebiliyor muyuz?** Risk rezervasyonu, intent/order/fill zinciri, tek giriş/çıkış, koruma, fee ve mutabakat. Fixture/paper üzerinden hata senaryoları geçer.

**Kapı 3 — Savunabiliyor muyuz?** Kayıtlardan her karar ve net sonuç açıklanır; yetkili yarışma hesabında doğrulanmış sınırlı canlı çalışma, ölçüm ve demo.

Örnek gün planı, entegrasyon durumuna göre uyarlanır:

| Zaman | Çıktı |
|---|---|
| 09.00–11.00 | Yarışma hesabı/ATK doğrulaması, veri kaydı ve ilk dashboard; emir/risk iskeleti |
| 11.00–13.00 | Tek kurulum, ajan aracı, risk/emir döngüsü ve kritik hata senaryoları |
| 13.00–17.30 | Kapılar geçince yetkili sınırlı canlı çalışma, gözlem ve execution düzeltmeleri |
| 17.30–19.30 | Özellikleri dondurma, resmî kurala göre giriş kesimi/kapanış, mutabakat ve teslim |

Canlıya çıkışı saate değil kabul kapılarına bağla. Geç başlanırsa kalan süreye göre kapsamı küçült; testleri atlayarak yetiştirme. Yeni giriş kesimini maksimum tutma süresi, çıkış/mutabakat payı ve 19.30 kuralından türet. Gün boyu zorunlu işlem sayısı uydurma.

Kritik doğrulamalar:

- Aynı anda iki niyet bütçeyi iki kez kullanamaz; tek worker sahipliği korunur.
- Miktar/precision/minimum ve fee sonrası envanter doğru; genişleyen stop miktarı artırmaz.
- %1 varsayılan/%2 üst sınır ve spot bakiye tavanı korunur; gerçekleşen risk bütçeden küçükse doğru raporlanır. Başabaşa taşıma R paydasını değiştirmez; yinelenen +2R tetikleri ikinci kez kâr satışı üretmez. TP/stop yarışında runner dahil mevcut envanter aşılmaz.
- Kayıp ACK, duplicate/erken fill, kısmi dolum ve cancel/fill yarışı çift emir/pozisyon/PnL üretmez.
- Restart ve API hatası boş bakiye/pozisyon sanılmaz; mutabakat öncesi giriş açılmaz.
- Eski/gap’li veri ve LLM hatası yeni girişi engeller; açık pozisyon yönetimi devam eder.
- Ledger’daki gerçek fee/PnL ile dashboard tutarlı; finansal kayıt başarısızken yeni emir gönderilmez.
- Replay’de gelecekteki veri sinyale sızmaz; eksik veriler ve simüle dolum sınırları görünürdür.
- Uzun süre işlem olmaması yalnız tanılama tetikler; risk/fee/stop kontrollerini gevşetmez. Fırsat sayaçları aynı adayı tekrar tekrar yeni fırsat saymaz; runner nedeniyle bloke edilen girişler görünürdür.
- Profil sürümü her karar/pozisyonda saklanır; gölge önerisi kendiliğinden canlı strateji olmaz. Bağlamsal seçim izinli parametre alanını aşmaz; sürüm değişikliği açık pozisyonları sessizce yeniden yönetmez.
- Yavaş/yanıtsız REST, sessiz WS, pong var ama eski book, sequence gap, bir paritenin takılması ve rate limit hata enjeksiyonları uygulanır. Reconnect sonrası backfill/warm-up bitmeden yeni giriş olmaz; tek reconnect ve sınırlı görev sayısı korunur.
- DB batch gecikmesi ve sonucu belirsiz commit senaryolarında yeni giriş kilidi ve kayıt tekilleştirmesi doğrulanır. Dashboard/analiz yükü kritik emir görevlerini aç bırakmaz; tüm ağ kesintisinde uygulanamayacak koruma eylemleri dürüstçe raporlanır.
- ATK sürümü, `site=tr`, yarışma profili ve gerçek araç şemaları doğrulanır. Ham write tool risk motorunu atlayamaz; MCP/CLI süreci ölümü ve kayıp yanıt çift emir üretmez. Streaming desteği bulunmadan polling tam order flow sayılmaz.

Süre daralırsa sembol sayısını, ek özellikleri ve görsel süslemeleri azalt. Risk, gerçek fill muhasebesi, mutabakat ve veri tazeliği çekirdek olarak kalır.

## 12. Death Kiss projesinden ne taşınır?

Mevcut strateji pump sonrası short ve daha uzun ufuk için tasarlanmış. Spotta birebir veya ters işaretle kullanma. Eski DK/entry-score eşikleri ve gözlem sıklığı yeni sisteme otomatik taşınmaz. Yorulma bilgisi ileride alım engeli/çıkış bağlamı olabilir; ilk gün yeni filtre olarak zorunlu değil.

Taşınacak bilgi: dinamik risk, rezervasyon, gerçek fill maliyeti, native koruma yaklaşımı, kayıp ACK, kısmi kapanış, restart/reconcile, veri kalite kontrolü ve test senaryoları. Mevcut kaynak kodun bulunması canlı entegrasyonun doğrulandığı anlamına gelmez. SQL/settings/SDK bağımlılıklarını kontrol et; bütün backend’i kopyalama. Somut kaynak haritası ve bilinen açıklar [teknik playbook’un 12. bölümünde](AGENTIC_TRADING_HACKATHON_PLAYBOOK.md#12-taşınacak-kaynak-kod-haritası).

## 13. Başlangıç talimatı

Bu dosyayı alan ajan:

1. Mevcut çalışma alanını ve uygulanabilir proje talimatlarını incele; bu dosyadaki hedef, referans hipotezler ve bağlayıcı sınırları ayır.
2. Yarışma rehberi/hesap/ATK bilgilerini bul; sadece eksik kritik bilgileri bir seferde sor. Verilen stack/stratejiyle hızlı başlangıç yapabilirsin; kullanıcının R sistemini veya önerilen kurulumu sorgulanamaz sayma. Daha uygun alternatif varsa gerekçesi, kanıt sınırı ve uygulama maliyetiyle öner; baştan sonsuz strateji tartışmasına dönme.
3. Canlı erişim beklerken fixture/paper, normalize veri modeli ve ilk dashboard’u kur.
4. Veri → kayıt → özellik → karar kartı akışını tamamla; ardından risk/emir yaşam döngüsünü bağla.
5. Kullanıcının %1 risk, +1R girişe stop, %30/%60/%10 çıkış yaklaşımını `retail_baseline_v1` olarak koru; alternatifleri ayrı sürümde ölç. İlk canlı risk alanı, günlük zarar bütçesi ve runner çıkışı eksikse netleştir; anlatılmış retail tercihleri tekrar sorma. Öğrenilmiş stratejinin otomatik canlı terfisini bu beyin fırtınasından yetkilendirilmiş sayma; bağımsız geliştirme/gölge değerlendirmeyi sürdür.
6. Her kapıda çalışan çıktıyı ve kalan somut sorunu kısa raporla. Gereksiz teknoloji/strateji ekleme.
7. Son teslimde çalıştırma komutları, test sonucu, canlı doğrulanan kapsam, bilinen eksikler ve demo akışını bırak.

## 14. Referanslar

Bu bağlantılar 11 Eylül 2026 konuşmasında incelendi; API, ücret ve erişim koşullarını uygulama anında yeniden doğrula.

- [Hackathon sayfası](https://komunite.com.tr/etkinlikler/agentic-trading-hackathon)
- [OKX TR API](https://tr.okx.com/docs-v5/)
- [OKX API — emir sözleşmeleri](https://www.okx.com/docs-v5)
- [OKX TR ücret duyurusu](https://tr.okx.com/en/help/update-on-transaction-fees-2) — yarışma hesabının gerçek ücretinin yerine geçmez.
- [Quantpylib kurulum ve kullanım koşulları](https://quantpylib.hangukquant.com/)
- [Quantpylib features](https://quantpylib.hangukquant.com/hft/features/)
- [Quantpylib event journal](https://quantpylib.hangukquant.com/tutorials/hft_event_journal/)
- [ClickHouse OLAP mimarisi](https://github.com/ClickHouse/clickhouse-docs/blob/main/docs/intro.md)
- [CME — anlamlı stop ve pozisyon büyüklüğü](https://www.cmegroup.com/education/courses/trade-and-risk-management/proper-position-size)
- [Howard Marks — The Indispensability of Risk](https://www.oaktreecapital.com/insights/memo/the-indispensability-of-risk) — riskten tümüyle kaçınmanın getiri/fırsat maliyeti bağlamı; bu botun kârlılığına kanıt değildir.
- [Bailey ve diğerleri — The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) — çoklu deneme ve geçmiş veride seçilmiş performansın sınırları.
- [PostgreSQL — toplu veri yükleme](https://www.postgresql.org/docs/17/populate.html)
- [OKX TR Agent Trade Kit](https://tr.okx.com/en/agent-tradekit)
- [ATK MCP/CLI rehberi](https://tr.okx.com/docs-v5/agent_en/)
- [Resmî ATK kaynak deposu](https://github.com/okx/agent-trade-kit)
- [ATK site/profil yapılandırması](https://github.com/okx/agent-trade-kit/blob/github-main/docs/configuration.md)
