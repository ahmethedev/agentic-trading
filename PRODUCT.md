# ThatsMyQuant — ürün yönü ve uygulama ek belgesi

Tarih: 12 Eylül 2026 · Durum: uygulanacak ürün yönü; özelliklerin tamamlandığı anlamına gelmez.

**Son revizyon:** Kullanıcı değerlendirme kriterlerinin değiştiğini bildirdi. Aşağıdaki ağırlıklar eski brief/playbook içindeki puan tablosunun yerine geçer. Ürün faydası ve kullanıcı deneyimi toplam %60'tır; ATK entegrasyonunun kapsamı ve derinliği %20'dir. Eski performans ağırlığına göre kapsam planlama. Bu değişiklik diğer yarışma kurallarının değiştiği anlamına gelmez.

## 1. Bu belgeyi nasıl kullanmalı?

Bu belge, [Agent Brief](AGENT.md) ile devam eden geliştirmeye ek yönlendirmedir. Önce mevcut uygulamanın durumunu incele; çalışan bileşenleri bu ürün akışına bağla. Sıfırdan yeniden başlama.

- **Bu belge:** güncel değerlendirme ağırlıkları, ürün kimliği, kullanıcı akışı, sohbet, strateji oluşturma/izleme, ATK entegrasyon kanıtı, anahtar güvenliği, UI/UX tasarım kuralları ve demo kapsamı.
- **Agent Brief:** strateji referansları, risk, execution, veri doğruluğu, ATK, timeout ve operasyonel kabul kapıları.

Ürün yönünde bu ek belge önceki “tek kurulumu açıklayan dashboard” tanımını genişletir. Önceki salt okunur dashboard önerisinin üzerine taslak oluşturma ve gölge çalışma kontrolleri eklenir. Risk/emir sözleşmeleri geçerliliğini korur. Bu genişleme tek başına yeni canlı strateji aktivasyonu veya risk limiti artışı yetkisi değildir; oturumda zaten verilmiş yetkiyi yeniden isteme.

Kullanıcının tercihi: trader deneyimini ve mühendisliğini görünür kılan, kullanışlı ve sunulabilir bir ürün; sınırlı hackathon süresinde ayrıntıda kaybolmadan çalışan bir çekirdek.

### Güncel değerlendirme ve karşılığı

Kaynak: kullanıcının bu oturumda aktardığı güncel kriterler. “Atk map integration depth” ifadesi bu belgede ATK/MCP entegrasyon kapsamı ve derinliği olarak ele alınmıştır; bağımsız bir “MAP” protokolü varsayılmaz.

| Kriter | Ağırlık | Üründe gösterilecek karşılık | Kanıt |
|---|---:|---|---|
| Functional utility and value | %30 | Piyasayı anlama, kendi stratejisini açıklama, yeni fikri çalıştırılabilir deneye dönüştürme ve takip | Aynı kullanıcı senaryosunun başlangıçtan sonuç ekranına çalışması |
| User experience and interaction | %30 | Anlaşılır ilk kullanım, sohbet + düzenlenebilir kartlar, tutarlı görsel dil, açık durum ve hata geri bildirimi | Hazır sorularla ve serbest girişle çalışan demo; klavye ve ekran boyutu kontrolleri |
| ATK integration depth | %20 | Piyasa → hesap/maliyet → emir yaşam döngüsü → fill/mutabakat zincirinde gerçek ATK kullanımı | Araç bazlı entegrasyon matrisi, gerçek çağrı izi ve hata senaryoları |
| System reliability and safety | %10 | Anahtar sınırı, izinler, risk kontrolü, timeout ve çift emir önleme | Doğrulanmış güvenlik/iyileşme senaryoları ve uygulanan saklama modeli |
| Innovation and uniqueness | %10 | Trader'ın kendi kuralını sorgulaması, tek değişiklikli deney ve kanıta dayanan açıklama | Baseline → değişiklik → gölge run → karşılaştırma akışı |

Kâr ve net PnL ürünün yararını değerlendiren önemli çıktılardır; yeni listede ayrı performans ağırlığı yoktur. Sunumu yalnız getiri grafiğine bağlama. Güvenlik puanının %10 olması temel güvenlik işlerini isteğe bağlı yapmaz. Araç sayısını artırmak için gereksiz alım/satım veya kapsam dışı türev/transfer özelliği ekleme.

## 2. Ürün fikri

**Çalışma adı: ThatsMyQuant.** Trader’ın piyasayı anlamak, kendi kurallarını incelemek, yeni bir fikri strateji taslağına dönüştürmek ve sonuçlarını takip etmek için kullandığı kişisel quant agent arayüzü.

Temel akış:

> Piyasayı incele → fikrini tarif et → açık kuralları gör → gölge çalıştır → sonuçları ve gerekçeleri incele → uygun koşullarda canlı sürümü yönet.

Sunum cümlesi:

> Yıllardır kullandığım işlem kurallarım var. ThatsMyQuant ile bu kuralları ölçüyorum, ajanın neden işlem aldığını görüyorum ve yeni fikirlerimi sermaye ayırmadan önce gözlemliyorum.

Doğal dille bot oluşturmayı veya backtest yapmayı tek başına benzersiz özellik diye sunma. Bizim ürün odağımız: kullanıcının kendi stratejisi, gerçek karar/emir kayıtları, kontrollü alternatif deneyi ve anlaşılır risk görünümünün aynı akışta buluşması. Rakiplerde bulunmadığı doğrulanmamış bir özellik için “ilk/tek” iddiası kullanma.

## 3. Hackathon kapsamı

### Öncelikli teslim

1. Piyasa özeti, strateji/pozisyon durumu ve sohbeti birleştiren tek uygulama ekranı.
2. Gerçek veri ve kayıtlara bağlı hazır soru butonları; serbest metinle aynı araçlara erişim.
3. Başlangıç stratejisinin kurallarını, sürümünü, kararlarını ve run durumunu gösteren strateji kartı.
4. Desteklenen bir şablondan doğal dille düzenlenebilir strateji taslağı oluşturma.
5. Mevcut stratejiyi kopyalayıp tek kuralı değiştirme ve en fazla bir alternatifi gölge modda çalıştırıp izleme.
6. Gerçek fill, maliyet ve net sonucu gösteren canlı çalışma görünümü; canlıya geçiş mevcut teknik kabul kapılarına bağlıdır.
7. Anahtarsız piyasa keşfi ve “OKX bağlantısı” görünümü: hesap/profil, çalışma modu, doğrulanmış erişim ve son bağlantı kontrolü; ham anahtar gösterilmez.
8. Ürün içinden açılan entegrasyon ayrıntısı: gerçekten kullanılan ATK araçları, kullanıcı akışındaki yerleri ve test/çalışma durumları.

İlk sürümde en fazla bir canlı strateji ve bir gölge alternatif yeterli. Gölge alternatif bağımsız simüle envanter taşır; canlı hesap bakiyesini tüketmez ve borsaya emir göndermez.

### Sonraya bırakılabilir

Genel amaçlı görsel strateji editörü, sınırsız serbest kod üretimi/çalıştırma, çoklu canlı portföy, strateji pazaryeri, herkese açık çok kullanıcılı servis, haber/sosyal medya entegrasyonu, geniş backtest optimizasyonu ve otomatik öğrenilmiş strateji terfisi. Yerel tek operatör demosu için kapsamlı üyelik sistemi gerekmez; özel hesap verisi veya yazma uçları ağa açılırsa kimlik doğrulama/yetkilendirme ertelenemez. Tam geçmiş backtest motoru ilk demo için zorunlu değildir; destekleniyorsa mevcut replay kullanılır.

Süre daralırsa şablon sayısını, grafik çeşitlerini ve geçmiş analiz kapsamını azalt. Veri ve emir doğruluğu ile çalışan sohbet → taslak → gölge izleme akışını koru.

## 4. Arayüz

Tek uygulama kabuğu içinde odaklı görünümler kullan. Genel bakış ilk ekrandır; Stratejiler ve Deneyler sekme/route olabilir. Her paneli aynı anda küçücük kartlara sıkıştırma. Ölçüler ve görsel sistem bölüm 13'te tanımlıdır.

| Alan | Kullanıcıya verdiği bilgi/eylem |
|---|---|
| Üst durum şeridi | LIVE/SHADOW/REPLAY, veri zamanı, hesap takma adı, açık risk, net sonuç, bağlantı durumu |
| Market | İzlenen pariteler, seçilen zaman ölçeğinde trend/range/geçiş/belirsiz bağlamı, hacim, spread ve veri kapsamı |
| My Strategies | Sürüm, kurallar, çalışma modu, son değerlendirme, pozisyon ve geçerli engel/WAIT nedeni |
| Ask My Quant | Hazır sorular, serbest sohbet, araçlardan gelen kanıtlar ve ilgili karta/grafiğe bağlantı |
| Experiments | Baseline/alternatif kural farkı, run dönemi, gözlem sayısı, maliyet varsayımları ve sonuç durumu |
| OKX bağlantısı | Hesap takma adı, bölge, mod, izin doğrulama durumu, son bağlantı testi ve anahtar saklama modelinin kısa açıklaması |

Sohbet cevabı gerektiğinde metin yanında piyasa kartı, kurallar kartı veya karşılaştırma açar. Her mesajda büyük grafik çizmek gerekmez. Teknik araç izi açılabilir bir ayrıntıdır; ana deneyim trader’ın sorusunu cevaplar.

Bekleme tek bir durum değildir: kurulum bekleniyor, teyit bekleniyor, risk nedeniyle elendi, veri eski, emir sonucu belirsiz gibi somut nedenler gösterilir. Run durumu ile tek adayın değerlendirme aşaması ayrı tutulur.

## 5. Sohbet ve hazır demo soruları

Hazır butonlar gerçek soruyu normal agent akışına gönderir; sabit başarı cevabı oynatmaz.

| Soru | Beklenen davranış |
|---|---|
| “Piyasanın şu anki fotoğrafını çıkar.” | İzlenen evren ve zaman ölçeğiyle rejim ölçümlerini, hacim/spread ve veri zamanını getir; yorumunu bu kapsamla sınırla |
| “Hangi paritelerde kurulum oluşuyor?” | Scanner’ın gerçek adaylarını ve eksik koşulları göster; aday oluşması emir önerisi veya fill değildir |
| “Stratejim nasıl çalışıyor?” | Aktif sürümden giriş, geçersizlik/stop, çıkış ve risk kurallarını anlaşılır biçimde açıkla |
| “Son işlemi neden aldık?” | O karar anında kaydedilmiş girdiler, gerekçe ve intent→emir→fill zincirini aç |
| “Neden işlem açmadık?” | Belirli dönemin aday/ret akışını sorgula; piyasa koşulları ile teknik kesintiyi ayır |
| “Bugün ne kadar risk aldık, maliyetimiz ne?” | Ledger ve risk servisinden açık/bekleyen risk, gerçekleşen fee ve net sonuçları getir |
| “1R’da stop’u entry’ye çekmeseydik ne olurdu?” | Aynı girişe bağlı çıkış deneyi öner veya mevcut sonucu getir; veri yetmiyorsa sonuç üretme |
| “Bu stratejiyi kopyala, başabaş kuralını değiştir.” | Desteklenen alternatifle yeni taslak sürüm ve okunabilir kural farkı oluştur |
| “Bu alternatifi gölge modda çalıştır ve durumunu göster.” | Doğrulanmış sürümle run oluştur, kimliğini ve gerçek durumunu göster; tekrar gönderim ikinci run yaratmasın |

Piyasa yorumunda fiyat/hacim ölçümleri ile ajanın çıkarımı ayırt edilir. Düşük trend gücü otomatik range sayılmaz; belirsiz/geçiş cevabı geçerlidir. İzlenen birkaç OKX paritesinden bütün piyasa hakkında kesin sonuç çıkarma. Güncel veri yoksa son geçerli zaman ve eksik kapsam görünür kalır.

Geçmiş işlem gerekçesini bugünkü grafik üzerinden yeniden uydurma. Risk/PnL hesaplarını LLM’ye yaptırma; hesaplanmış değerleri yorumlat. Veri eksikliği, timeout ve hesaplanmamış metrik normal cevap durumlarıdır.

## 6. Strateji oluşturma ve çalışma modeli

Doğal dil → desteklenen şablon ve alanlara çeviri → sunucu tarafında doğrulama → kullanıcıya okunabilir kurallar kartı → kaydedilmiş sürüm → seçilmiş çalışma modu.

İlk şablon mevcut geliştirilmekte olan strateji olsun. Yeni fikrin desteklenmeyen bölümünü açıkça belirt; sessizce başka bir kurala dönüştürme. Maddi belirsizlikte yalnız eksik parametreyi sor; mevcut stratejiyi kopyalarken bilinen tercihleri yeniden sorma. Model çıktısını serbest Python/shell kodu olarak yürütme.

Asgari kavramlar; mevcut modellere uyarlanabilir:

- `Strategy`: ad, açıklama ve kullanıcı fikri.
- `StrategyVersion`: şablon, evren, zaman ölçekleri, giriş/teyit/çıkış kuralları, risk profili referansı, üst sürüm ve kural farkı. Run’a bağlanan sürüm değişmez.
- `Run`: sürüm, LIVE/SHADOW/REPLAY modu, durum, başlangıç/bitiş, veri aralığı, maliyet/dolum modeli ve son heartbeat.
- `Experiment`: baseline/alternatif run referansları, değişen kural, karşılaştırma yöntemi ve kanıt durumu.

Taslak kaydetmek run başlatmak değildir. Run başlatmak da fill oluştuğu anlamına gelmez. Çalışma sırasında düzenleme yeni sürüm üretir; mevcut pozisyon planını sessizce değiştirmez.

“Yeni girişleri durdur”, “gölge çalışmayı sonlandır” ve “canlı pozisyonu kapat” ayrı eylemlerdir. Girişleri durdurmak mevcut pozisyon korumasını kapatmaz. İlk sürümde canlı yönetim için mevcut yetkili kontrol akışı kullanılabilir; sohbetten bütün canlı yazma eylemlerini desteklemek zorunlu değildir.

Kullanıcının `retail_baseline_v1` deneyim aktarımı korunur: varsayılan %1 risk, mevcut %2 operasyonel üst sınır, +1R’da gerçek girişe stop, ilk miktarın %30’u +2R, %60’ı +2,5R, %10 runner. Bunlar kârlılığı kanıtlanmış evrensel kurallar değildir; değişiklikler ayrı deney olarak ele alınır. Ayrıntılı hesap sözleşmesi Agent Brief’tedir.

## 7. Agent ve mevcut mimariye bağlantı

```text
React çalışma alanı: sohbet + kartlar + hazır sorular
                         ↓
FastAPI → agent/harness → doğrulanmış uygulama araçları
                              ├─ piyasa/karar/ledger sorguları → PostgreSQL
                              ├─ strateji taslağı/sürüm servisi
                              └─ run/deney servisi → gölge evaluator

Mevcut canlı worker → deterministik risk → emir yöneticisi → OKX ATK MCP → OKX TR
                         ↓
                 karar/emir/fill kayıtları → aynı PostgreSQL → arayüz
```

Aşağıdaki adlar önerilen **bizim uygulama araçlarımızdır**; hazır OKX ATK araçları olduklarını varsayma:

`get_market_overview`, `get_strategy`, `explain_decision`, `get_risk_summary`, `create_strategy_draft`, `clone_strategy`, `start_shadow_run`, `get_run_status`, `compare_runs`.

Önce mevcut Python servis fonksiyonlarını şemalı araçlar olarak kullan. Bunları ileride başka agentların kullanacağı bir MCP sunucusuna açmak mümkün; hackathon için ikinci MCP sunucusu kurmak şart değil. UI ve agent aynı servis kurallarını kullanır. OKX erişimi mevcut ATK connector üzerinden devam eder; sohbet ham emir araçlarıyla risk motorunu atlamaz.

Python/asyncio + FastAPI + Pydantic/Decimal + React/Vite + mevcut grafik kütüphaneleri + tek PostgreSQL korunur. Pi veya yeni framework bu ürün yönünün zorunlu bağımlılığı değildir.

Sohbet/analiz yavaşlığı canlı risk/koruma döngüsünü bloke etmez. Araç çağrıları sınırlı süre/sonuç boyu kullanır. Yazma araçlarında istek kimliği ve kalıcı sonuç kaydıyla çift taslak/run oluşması önlenir; timeout sonrası mevcut sonuç sorgulanır. Yeni sohbet isteği her seferinde tüm piyasa geçmişini çekmez.

Mesaj, araç çağrısı sonucu/durumu, zaman ve ilgili strategy/version/run/decision referansları aynı PostgreSQL’de tutulur. Model/config sürümü ve kullanılan veri referansları kaydedilir. Gizli anahtarlar veya modelin özel düşünce zinciri saklanmaz; kullanıcıya kısa gerekçe ve gerçek araç sonuçları gösterilir.

## 8. Deneylerin dürüst karşılaştırılması

İlk deney için yalnız başabaş kuralını değiştirmek uygun bir örnektir. İki farklı soru birbirine karıştırılmaz:

1. **Aynı girişin çıkış deneyi:** giriş/ilk miktar/ilk stop sabit, yalnız çıkış kuralı farklı. Tam portföy getirisi iddiası değildir.
2. **Bağımsız strateji run’ları:** her kolun kendi simüle pozisyonu, nakdi ve risk durumu vardır. Farklı çıkış zamanı yeni adaylara katılımı da değiştirir; her iki kolun bütün girişleri aynı olmak zorunda değildir.

Karşılaştırmada yöntem, dönem, veri çözünürlüğü, fee/slippage/dolum varsayımları ve tamamlanmış/açık gözlem sayısı görünür olur. Canlı fill ile simüle fill aynı kesinlikte sunulmaz. Mum içinde hem stop hem hedef görülüyorsa sıralamayı uydurma; belirsizlik veya tanımlı muhafazakâr varsayım kaydedilir.

Yeni fikir geçmişte deneniyorsa “replay”, bundan sonra gelen veride izleniyorsa “shadow” olarak etiketlenir. Geçmiş veri yetersizse gölge gözlem başlat; geçmiş sonuç varmış gibi gösterme. Birkaç saatlik örneklemden kalıcı edge veya öğrenilmiş üstünlük çıkarma. “Kanıt yetersiz” geçerli deney sonucudur.

## 9. Üç dakikalık demo

1. **0:00–0:20 — Problem ve güven:** Kişisel işlem kurallarını ölçme ihtiyacını anlat. Çalışma alanında hesabın/modun ve bağlantı durumunun açık olduğunu göster; kullanılan anahtar saklama modelini bir cümleyle belirt.
2. **0:20–0:55 — Fayda ve etkileşim:** “Piyasanın fotoğrafını çıkar” ile zaman damgalı kartı aç. Bir pariteyi seçip sohbet bağlamına al; kısa bir takip sorusu sor.
3. **0:55–1:40 — Fikirden deneye:** Stratejiyi kopyala, tek kuralı değiştir, okunabilir farkı göster ve gölge run başlat. Başlatma durumunun gerçek backend'den geldiğini göster.
4. **1:40–2:10 — Davranış ve sonuç:** “Son işlemi neden aldık?” veya “Neden işlem açmadık?” ile gerçek kayıtları aç. Mevcut deney sonuçlarında maliyeti ve örneklem sınırını göster.
5. **2:10–2:40 — ATK derinliği:** Bir cevabın dayandığı fiyat, hacim ve likidite ölçümlerini ilgili gerçek araç çağrılarıyla göster; hesap/fee ve varsa emir→fill→mutabakat zincirine bağla. Benzersiz doğrulanmış araç sayısını ortamıyla birlikte göster.
6. **2:40–3:00 — Güvenilirlik:** Etiketli test/replay kaydından timeout→belirsiz sonuç→mutabakat davranışını veya eski veride giriş engelini göster; uygulanan anahtar güvenliği ve bilinen sınırla bitir.

Demo sırasında uygun piyasa kurulumu oluşması şart değildir. Kayıtlı replay gerekiyorsa modu açıkça göster; yarışmanın canlı performansı ile birleştirme. Hazır soru gerçek backend’e gider; fixture verisi canlı gibi gösterilmez.

## 10. Geliştiren agent için uygulama sırası ve kabul

1. Mevcut kodu ve çalışma durumunu incele; piyasa, karar, strateji, risk ve run servislerinden hangilerinin hazır olduğunu çıkar. Çalışan parçaları yeniden yazma.
2. Bölüm 13'teki token/layout sistemini ortak bileşenlerle kur; bağlantı ve ilk kullanım görünümünü ekle. Yeni ürün ekranında mevcut terminal tarzı genel CSS'i gerektiğinde kapsamlandır; bütün repoyu yeniden tasarlama.
3. Önce okuma araçlarıyla piyasa özeti, strateji açıklaması ve karar/WAIT sorgusunu uçtan uca çalıştır.
4. Desteklenen şablondan taslak/sürüm oluşturma ve tek değişiklikli kopyalamayı ekle.
5. En fazla bir gölge alternatifin başlatılması, durumunun izlenmesi ve sonuçlarının doğru etiketlenmesini tamamla.
6. Mevcut canlı worker ve ledger görünümünü bağla; teknik kabul kapılarını ürün demosu uğruna atlama.
7. ATK entegrasyon kanıtını çağrı kayıtlarından üret. Anahtar akışını, yetki sınırlarını ve hata durumlarını doğrula; bölüm 14'teki görsel/etkileşim kabulünü tamamla.

Anlamlı kabul kontrolleri:

- Piyasa/işlem sorularındaki sayılar gerçek servis yanıtıyla eşleşir; eski/eksik veri veya araç timeout’u görünürdür.
- Sohbet ve dashboard aynı strategy version/run/decision kaydını gösterir.
- Desteklenmeyen veya geçersiz strateji taslağı çalıştırılamaz; normal kullanıcı fikri yürütülebilir serbest koda dönüşmez.
- Tekrarlanan başlatma isteği aynı run’a döner; gölge run borsaya yazma çağrısı yapmaz.
- Düzenlenen taslak aktif canlı sürümü veya açık pozisyonu değiştirmez; sohbet kesintisi korumayı durdurmaz.
- Demo soruları gerçek araçlara ulaşır; LIVE/SHADOW/REPLAY ve gerçekleşen/simüle sonuç ayrımı tüm kartlarda tutarlıdır.

Teslimde uygulanan, kısmen çalışan ve sonraya kalan özellikleri belirt. Kullanıcıya her rutin UI/servis seçimini tekrar sormadan bu kapsam içinde ilerle.

## 11. ATK entegrasyonu: kapsam, derinlik ve kanıt

MCP aracı, alttaki HTTP endpoint'i ve bizim uygulama aracımız ayrı kavramlardır. `explain_decision` gibi yerel bir wrapper'ı yeni OKX endpoint'i sayma. Aynı aracı 100 kez çağırmak 100 entegrasyon değildir. `tools/list` ile keşfedilmiş olması uygulamada bağlanıp doğrulandığını kanıtlamaz.

Aşağıdaki araç adları [resmî ATK rehberindeki](https://tr.okx.com/docs-v5/agent_en/) örneklerdir. Kurulu sürümde şema, bölge ve hesap desteğini doğrula. Liste uygulama hedefidir; mevcut entegrasyon sayısı beyanı değildir.

| Kullanıcı akışı | ATK araç adayları | Derinlik nasıl görünür? |
|---|---|---|
| Piyasa tarama ve parite kartı | `market_get_tickers`, `market_get_ticker` | Aynı fiyat/hacim verisi evren seçiminde, kartta ve sohbet cevabında kullanılır |
| Grafik ve geçmiş bağlam | `market_get_candles`, `market_get_history_candles` | Warm-up, kapanmış mum kontrolü, geçmiş doldurma ve grafik/sinyal tutarlılığı |
| Likidite ve akış | `market_get_orderbook`, `market_get_trades` | Spread/maliyet ve veri yeterliyse trade imbalance; gap/tazelik etkisi |
| Hesap, kapasite ve maliyet | `account_get_balance`, `account_get_fee_rates`, `account_get_config` | Hesap bağlamı, gerçek fee, kullanılabilir bakiye ve risk kontrolü |
| Emir yönetimi | `spot_place_order`, `spot_cancel_order`, `spot_get_order` | Tek intent, risk rezervasyonu, kısmi fill, cancel yarışı ve UNKNOWN toparlanması |
| Takip ve mutabakat | `spot_get_open_orders`, `spot_get_fills`, `spot_get_order_history` | Restart sonrası envanter/ledger doğruluğu, gerçek fee ve emir geçmişi |

Bu tablo 15 farklı araç adayı içerir. Kapsam uygunsa tamamını anlamlı akışa bağla; yetişmeyeni planlandı olarak göster. Puan için gereksiz emir gönderme. Destek doğrulanırsa native koruma/algo emirleri veya hesap hareketleri daha derin kullanım sağlayabilir; mevcut spot çekirdeği tamamlanmadan yeni ürün kategorilerine dağılma.

Derinliği şu zincirle göster: **gerçek çağrı → doğrulanmış/normalize edilmiş veri → kullanıcı kararı veya uygulama eylemi → kalıcı kayıt → hata/toparlanma davranışı.** Sadece fiyatı metin olarak döndürmek ile bakiye+fee+likiditeyi miktar hesabında kullanıp gerçek fill ile uzlaştırmak farklı derinliklerdir.

Geliştiren agent `docs/ATK_INTEGRATION_EVIDENCE.md` veya mevcut eşdeğer raporu gerçek kod/çalışma kayıtlarından üretir. Her araç için sürüm/şema, ürün akışı, kod referansı, durum, doğrulama ortamı/zamanı, çağrı veya test referansı ve ele alınan hata belirtilir. Alttaki endpoint eşlemesi kaynak koddan doğrulanabiliyorsa ayrı sütun olur; tahmin edilmez.

Durumları ayır: **planlandı / uygulandı / fixture ile doğrulandı / borsa demo ortamında doğrulandı / yetkili canlı hesapta doğrulandı.** Public gerçek piyasa çağrısı hesabın canlı yazma yetkisinin doğrulandığı anlamına gelmez. Son başarısız çağrı ve bilinen kısıt da görünür olur.

Ürün içindeki “Entegrasyon ayrıntıları” görünümü benzersiz doğrulanmış araç sayısını ve ilgili iş akışlarını gösterir. Çağrı izi: araç adı, zaman, süre, başarı/hata/UNKNOWN, veri zamanı, cache/canlı kaynak ve decision/run referansı. Gizli bilgiler, imza, hesap kimliği ve ham hassas gövdeler gösterilmez. ATK'nın model tarafından ve deterministik worker tarafından çağrılan araçları ayrı açıklanabilir; ikisi de gerçek entegrasyondur.

## 12. API anahtarı ve finansal uygulama güvenliği

### İlk teslim için net saklama kararı

**Hackathon varsayılanı yerel, tek operatörlü uygulamadır. Piyasa keşfi için kullanıcıdan anahtar isteme.** Özel hesap/işlem erişimi için operatörün önceden yapılandırdığı yarışma alt hesabı ATK profiline bağlan. İlk sürümde ziyaretçilerden gerçek anahtar toplayan genel bir form açma. “OKX bağlantısı” ekranı seçili profilin durumunu ve kontrol sonucunu gösterir; uygulanmamış OAuth veya otomatik yetkilendirme akışı taklit etmez.

Yerel demo: credential üçlüsü (API key, secret, passphrase) repo dışında, yalnız ilgili OS kullanıcısının okuyabildiği ATK profilinde bulunur; Unix dizin izni `0700`, dosya `0600` hedeflenir. Dosya izni **şifreleme değildir**. Bu sürümde plaintext yerel profil kullanılıyorsa sunumda “şifreli kasada tutuyoruz” denmez. PostgreSQL'e yalnız profil referansı, takma ad, bölge/mod ve doğrulama metadatası yazılır; anahtarın ikinci kopyası yazılmaz. ATK profil/bölge davranışı seçilen [resmî yapılandırma sürümünden](https://github.com/okx/agent-trade-kit/blob/github-main/docs/configuration.md) doğrulanır.

Uygulama loopback'e bağlanır; yazma ve özel hesap uçları operatör oturumuyla korunur. Origin/Host doğrulaması ve gerekiyorsa CSRF kontrolü uygulanır; yalnız CORS veya localhost kullanmak yetkilendirme sayılmaz. Dışarıya demo gerekiyorsa hesap anahtarıyla çalışan yerel servisi anonim tünelle açma; ayrılmış salt okunur, hassas verileri azaltılmış demo kullan veya aşağıdaki sunucu şartlarını tamamla.

### Kullanıcı anahtarı kabul eden sunucu sürümü

Bu akış ürünleşme tasarımıdır; public onboarding açılacaksa önkoşuldur. Yerel demo için ikinci bir altyapıyı hemen kurma.

1. Kimliği doğrulanmış kullanıcı “OKX bağla” ekranında API key, secret ve passphrase girer. Ayrı bir form kullanılır; sohbet, prompt veya URL parametresi kullanılmaz. TLS üzerinden backend'e gönderilir. Browser storage, analytics/session replay, request-body logları ve hata izlerine alınmaz; işlem bitince form temizlenir. Backend tekrar secret döndürmez.
2. Kalıcı saklama için uygulama kararı: aynı PostgreSQL'de **AES-256-GCM ile şifreli credential**, ayrı yönetilen anahtar. Hazır kripto kütüphanesi; her şifrelemede yeni nonce, authentication tag ve key version; owner/connection kimlikleri authenticated data olarak bağlanır. Şifreleme anahtarı DB/repo/frontend'de tutulmaz; sunucunun secret manager/KMS erişimiyle yönetilir. Anahtarın tekrar imzalama için çözülmesi gerektiğinden hash saklamak çözüm değildir. [OWASP şifreli saklama rehberi](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
3. `CredentialProvider` yalnız yetkili execution bileşenine ihtiyaç anında erişim verir. Worker/ATK sırları bellekte kullanır; global env veya ortak profil dosyası hesaplar arasında değiştirilmez. Çok kullanıcılı sürümde bağlantı başına izole ATK oturumu gerekir. ATK'nın seçilen sürümde desteklediği secret aktarım yolu doğrulanır; komut satırı argümanlarında secret yoktur. Şifreli DB'den sonra kalıcı plaintext profil üretmek saklama garantisini bozar.
4. Her connection/strategy/run/ledger erişiminde sunucu tarafı sahiplik ve eylem yetkisi kontrol edilir; istemcinin gönderdiği `user_id` yetki kanıtı değildir. Cookie oturumunda HttpOnly/Secure/SameSite ve CSRF politikası; WebSocket aboneliklerinde aynı sahiplik kontrolü uygulanır. [OWASP yetkilendirme rehberi](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
5. Anahtar değiştirme, erişimi durdurma, silme ve olay kaydı tasarlanır. Yerel kopyayı silmek borsadaki anahtarı iptal etmez; borsa iptali ayrıca doğrulanır. Yedek saklama/silme politikası açıklanır. Şifreleme uygulama sunucusu ele geçirildiğinde tam koruma garantisi değildir. [OWASP secret yaşam döngüsü rehberi](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

### Yetki sınırı ve bağlantı UX'i

- Hesap görüntüleme için Read; canlı işlem gerekiyorsa ayrıca Trade. Para çekme yetkisi istenmez; transfer/withdrawal araçları uygulama allowlist'inde bulunmaz. Uygun sabit çıkış IP'si varsa venue IP kısıtı uygulanır. İzinler venue'den doğrulanamıyorsa “doğrulanamadı” denir; tahmini yeşil güvenlik rozeti kullanılmaz.
- Form/profil akışı: bölge ve ortamı seç → erişim testi yap → doğrulanan yetkileri göster → hesabı bağla. Bağlantı testi emir göndermez. Hesabın bağlanması canlı stratejiyi otomatik başlatmaz.
- UI iki ayrı durumu açık gösterir: **veri/hesap bağlantısı** ve **run modu**. OKX demo hesabı, uygulama içi SHADOW simülasyonu ve REPLAY aynı şey değildir.
- Canlı başlatma destekleniyorsa hesap, pariteler, strateji sürümü ve risk bütçesiyle somut aktivasyon özeti göster. Tanımlı yetki içindeki her otonom emir için tekrar popup açma. Bilinçli aktivasyon sonrası deterministik kontroller sürer.
- “Bağlantıyı kes” mevcut emirleri veya pozisyonları kapatmış sayılmaz. Yeni girişleri durdur; açık/bekleyen emirleri ve koruma etkisini göster. Acil anahtar iptalinde uygulama korumasının devam edeceğini iddia etme; borsa tarafında ne kaldığı raporlanır.
- LLM ve sohbet araçları credential deposuna, ham imza başlıklarına veya key-bearing config'e erişemez. Modele yalnız ilgili soruya gereken hesap özeti gönderilir; public model sağlayıcısına hiç veri gitmediği iddiasında bulunma. Tool sonuçları/markdown güvenilmeyen içeriktir; HTML/script ve yetkisiz write talimatı yürütülmez.

Güvenlik kabulü: sahte canary credential ile log/trace/UI sızıntısı kontrolü; Read-only erişimle yazma reddi; sunucu sürümünde başka kullanıcıya ait connection/run kimliğine erişim reddi; değişmiş ciphertext/tag ile çözme hatası; iptal edilmiş erişimle yeni çağrı engeli; mevcut timeout/reconcile testleri. Gerçek key'leri test fixture'ına koyma. Uygulanmayan kontrolleri çalışıyor diye raporlama.

## 13. UI/UX tasarım yönetmeliği

### Görsel yön ve bilgi hiyerarşisi

**Açık zeminli, sakin ve okunaklı bir finans çalışma alanı.** Koyu lacivert metin, mavi aksiyon, geniş grafik alanı ve kontrollü veri yoğunluğu. Mevcut frontend'in genel monospace/karanlık terminal görünümü yeni ürünün zorunlu kimliği değildir. Yeni kabukta tokenları kapsamlandır; ilgisiz ekranları bozma. İlk teslimde tek tema yeterli.

Ekran önce “Ne oluyor?”, sonra “Benim stratejim ne yapıyor?”, sonra “Sıradaki anlamlı eylem ne?” sorularını cevaplar. Teknik ayrıntı açılır panelde yer alır. Her modüle aynı büyüklükte kart verme; ana grafik ve aktif strateji baskın, yardımcı ölçümler ikincil olur. Rastgele gradyan, cam efekti, neon çizgi, büyük dekoratif logo ve sürekli yanıp sönen fiyatlar ekleme.

### Layout ve responsive davranış

- **1366–1440 px masaüstü:** solda 208 px navigasyon; üstte 56 px bağlam/hesap çubuğu. Çalışma alanında 24 px dış boşluk, 24 px sütun aralığı; sağda yaklaşık 340 px sohbet, kalan alan grafik/strateji içindir. İç grid `minmax(0, 1fr)` kullanır; uzun içerik tüm sayfayı taşırmaz.
- Sol navigasyon: Genel bakış, Stratejiler, Deneyler; altta OKX bağlantısı. Menü adedi bu kapsamı aşmaz. Entegrasyon ayrıntısı bağlantı ekranından veya cevap içinden açılır.
- Genel bakış: kısa piyasa özeti ve en fazla dört ana metrik → fiyat/hacim grafiği + seçili parite → aktif strateji ve son kararlar. Grafik masaüstünde yaklaşık 300–360 px yüksekliğinde kalır; 768 px ekran yüksekliğinde temel durum ve ana eylem ilk görünümde bulunur.
- **1200 px altında:** sohbet sağ panel yerine düğmeyle açılan drawer veya sekme olur. **900 px altında:** navigasyon daralır, içerik tek sütuna geçer. **Mobil:** başlık + odaklı sekmeler; veri tablosu kendi alanında kayar veya özet satıra döner. Sayfanın tamamında yatay scroll oluşmaz.
- Sohbet geçmişi kendi içinde kayar; giriş alanı görünür kalır. Kullanıcı eski mesajı okurken yeni cevap zorla aşağı kaydırmaz; “Yeni cevap” bağlantısı sunar. Drawer aç/kapat seçili stratejiyi ve yazılmamış metni kaybetmez.

Örnek masaüstü iskeleti:

```text
┌────────────────┬─────────────────────────────────────────────────┐
│ ThatsMyQuant   │ Genel bakış           OKX TR · hesap · run modu │
│                ├───────────────────────────────┬─────────────────┤
│ Genel bakış    │ Piyasa özeti · veri zamanı    │ Ask My Quant    │
│ Stratejiler    │ 4 ana metrik                  │ Hazır sorular   │
│ Deneyler       │                               │                 │
│                │ Parite · fiyat/hacim grafiği   │ Cevap + kanıt   │
│                │                               │ Strateji kartı  │
│                │ Aktif strateji · son kararlar │                 │
│ OKX bağlantısı │                               │ Mesaj yaz…      │
└────────────────┴───────────────────────────────┴─────────────────┘
```

### Renk tokenları

Bu değerleri ortak CSS değişkenleri/theme tokenları olarak kullan; bileşenlerde bağımsız renkler uydurma.

| Token | Değer | Kullanım |
|---|---|---|
| `--canvas` | `#F6F7F9` | Uygulama zemini |
| `--surface` | `#FFFFFF` | Grafik, form ve içerik yüzeyi |
| `--surface-muted` | `#EEF1F6` | İkincil alan / hover |
| `--text` | `#17233B` | Başlık ve ana metin |
| `--text-muted` | `#5F6B7A` | Yardımcı bilgi; kritik bilgiyi daha fazla soldurma |
| `--border` | `#D8DEE8` | Dekoratif ayırıcı |
| `--control-border` | `#78859A` | Form sınırı ve etkileşimde görünür kontur |
| `--primary` | `#3159D9` | Ana buton, seçili öğe ve bağlantı |
| `--primary-soft` | `#EAF0FF` | Seçili öğe arka planı; metin primary |
| `--positive` | `#11785B` | Pozitif finansal değer / doğrulanmış başarı |
| `--negative` | `#B93843` | Negatif finansal değer / kritik hata |
| `--warning` | `#8A5700` | Eski veri, dikkat veya belirsiz işlem sonucu |

Primary butonda beyaz yazı kullan. Yeşili bütün CTA'lara yayma; “strateji oluştur” bir finansal kazanç değildir. Pozitif/negatif değerlerde +/− işareti ve etiket de bulunur. Modlar yalnız renk ile ayrılmaz: “LIVE · Gerçek hesap”, “SHADOW · Simülasyon”, “REPLAY · Geçmiş veri” metni görünür olur.

### Font, ölçü ve bileşenler

- UI: **IBM Plex Sans**, yedek `system-ui, -apple-system, Segoe UI, sans-serif`. Fiyat/ID/kısa sayısal kolonlar: **IBM Plex Mono**, yedek `ui-monospace, monospace`. Lisansı uygun font dosyalarını yerel paketle; demo çalışmasını harici font isteğine bağlama. Sohbetin tamamını monospace yapma.
- Sayfa başlığı 26/32 px, bölüm başlığı 18/26 px, gövde 15/24 px, sohbet 16/25 px, tablo 14/20 px, yardımcı etiket 12/18 px. Önemli finansal değerler 24–28 px; 400/500/600 ağırlıkları yeterli. Uzun büyük harf etiketlerden kaçın.
- Sayılarda `tabular-nums`; ondalık hassasiyet enstrümana göre, para birimi görünür. UI'da `tr-TR` biçimi; sunucuda sayısal veri locale bağımsız kalır. Para/R/% birimleri karıştırılmaz; eksik değer “—” ve açıklamasıyla gösterilir, sıfır yazılmaz.
- Boşluk ölçeği: 4/8/12/16/24/32 px. Panel iç boşluğu 20–24 px; köşe 10–12 px, input/button 8 px. Hafif border; gölge yalnız drawer/modal gibi katman ayrımında. Bir paneli gereksiz iç içe kartlarla bölme.
- Ana buton yüksekliği 40–44 px; ekranda birincil eylem belirgin olsun. Tablo satırı yaklaşık 44 px. İkonlar aynı çizgi stilinde 18–20 px; kritik kontroller metin etiketi taşır. Ekranın farklı yerlerinde aynı eyleme farklı isim verme.

### Etkileşim kuralları

1. **İlk kullanım:** anahtarsız “Piyasayı keşfet” ile değer göster. Hesap gerektiren özellikte bağlantı açıklaması sun. Boş strateji ekranında tek bir başlangıç şablonu ve “Strateji oluştur” eylemi vardır.
2. **Sohbet:** önce kısa sonuç, sonra kanıt/ölçüm, ardından ilgili eylem. “Piyasa verileri alınıyor” gibi gerçek araç aşaması göster; sahte düşünce akışı veya uydurma yüzde güven yazma. Kartlar aynı API verisini kullanır.
3. **Strateji oluşturma:** Fikir → Kurallar → Çalışma modu. Her adımda önceki giriş korunur. Kural kartında değişen alan vurgulanır, varsayılanlar etiketlenir; ham JSON düzenlemek zorunlu değildir. Varsayılan başlatma eylemi “Gölge çalıştır”dır.
4. **Başlatma/izleme:** kayıt/run sonucu doğrulanmadan “Başladı” gösterme; istek sürerken ikinci gönderimi engelle. Sunucu da idempotency uygular. Sonucu belirsiz bir yazma isteğinde “Tekrar başlat” yerine “Durumu kontrol et” kullan.
5. **Kontroller:** “Yeni girişleri durdur” ile “Pozisyonu kapat” görsel ve işlevsel olarak ayrılır. Geri alınabilir okuma/taslak adımlarına onay modalı koyma. Canlı para etkisi olan yeni yetki/aktivasyon akışında hesap/sürüm/risk özeti göster.
6. **Durumlar:** her veri alanında loading, boş, hata, kısmi/eski veri ve başarılı durum tasarlanır. Bilinen son değer tutuluyorsa yaşı görünürdür. Başarı toast'u kritik sonucun tek kaydı değildir; kart/run durumu kalıcıdır.
7. **Grafik:** fiyat+hacim, gerçek fill işaretleri ve seçili stop/hedef yeterli. Sinyal ile fill farklı işaretlenir. Simüle işlemler açık etiket taşır. Hover bilgisi yanında erişilebilir metin/tablo özeti bulunur; gereksiz indikatör kalabalığı yaratma.
8. **Hareket:** 120–180 ms kısa geçişler; grafik/sohbet yenilemesinde layout sıçraması yok. Kullanıcının reduced-motion tercihini uygula. Sürekli animasyon ve ses yok.

### Erişilebilirlik

Normal metinde en az 4.5:1, büyük metinde 3:1 kontrast hedefi; anlamlı kontrol sınırı ve focus göstergesinde 3:1 kontrolü. Klavye ile tüm akış çalışır; görünür focus, doğru label, modal focus yönetimi ve kapanınca odağı geri verme gerekir. Renk tek bilgi taşıyıcısı değildir. Dokunma hedefini ürün tercihi olarak en az 44×44 px tut; yoğun tabloda erişilebilir eylem menüsü kullan. %200 zoom'da ana işlemler erişilebilir kalır. Bunlar tasarım/kabul hedefidir; kontrol edilmeden WCAG uyumu iddia edilmez. [W3C WCAG 2.2 hızlı başvuru](https://www.w3.org/WAI/WCAG22/quickref/)

## 14. Ürün ve görsel teslim kabulü

Ürün faydasını da ölç: ilk kullanılabilir piyasa cevabına kadar süre, taslaktan gölge run'a tamamlanma süresi, tamamlanan/başarısız kullanıcı akışları ve araç/cevap gecikmesi. Küçük demo örneklemindeki ölçümleri gerçek kullanıcı araştırması veya genel performans garantisi diye sunma. ATK çağrı adedini ürün başarısı metriğiyle karıştırma.

- 1440×900 ve 1366×768 masaüstünde grafik, mod, veri zamanı ve ana eylem okunur; 390 px mobil genişlikte sayfa taşmaz. En az bir klavye-only akış ve %200 zoom kontrolü yapılır.
- Piyasa keşfi → strateji açıklaması → tek kural değişikliği → gölge başlatma → run takibi yolculuğu uçtan uca tamamlanır. Hazır soru dışında en az bir serbest takip sorusu da çalışır.
- Bağlantı yok / Read-only / veri eski / LLM timeout / emir UNKNOWN / boş deney durumları görsel olarak kontrol edilir. Hata metni somut sonraki adımı anlatır.
- Canlı ve simüle sonuçlar aynı toplamda birleştirilmez. Yarım kalmış örnekler kazanç/kayıp veya sıfır diye sayılmaz. Fiyat-R ile net R ayrı etiketlidir.
- Araç sayısı gerçek entegrasyon raporuyla eşleşir; planlanan ve doğrulanmış araçlar ayrı sayılır. Kanıt paneli key, secret, passphrase veya imza içermez.
- Bağlantı görünümündeki saklama/izin ifadeleri gerçek uygulamayla eşleşir. Yerel plaintext profil kullanan demo şifreli vault veya çok kullanıcı izolasyonu iddia etmez.
- Temel ekranların gerçek render'ı incelenir; font yüklenmemesi, uzun Türkçe metin, çok büyük/küçük fiyat, loading ve hata durumu denenir. Yalnız component kodunu okumak görsel doğrulama sayılmaz.

Son teslim özeti beş kriterle eşleşsin: hangi kullanıcı işi çözüldü; hangi etkileşim çalışıyor; kaç ATK aracı hangi ortamda doğrulandı; hangi güvenlik/iyileşme kontrolü test edildi; hangi deney akışı özgün ürün değerini gösteriyor. Mevcut brief'i geliştiren agent bu ek belgedeki önceliklerle devam eder; çekirdeği yeniden yazması gerekmez.
