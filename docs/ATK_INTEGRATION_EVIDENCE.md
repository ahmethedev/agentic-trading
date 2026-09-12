# ATK entegrasyon kanıtı — ilk envanter

12 Eylül 2026 · paket: `@okx_ai/okx-trade-mcp` 1.4.6 (vendor/atk kilidi).
Bu ilk envanter kalıcı çağrı telemetrisi değildir. Üründe doğrulanmış benzersiz
araç sayısı henüz yayımlanmaz; allowlist sayısı doğrulanmış çağrı sayılmaz.

| Araç / grup | Uygulamadaki yer | Kanıt durumu |
|---|---|---|
| market_get_instruments | worker.py → lot/minimum/tick sözleşmesi | Uygulandı; prod instruments kayıtları mevcut |
| market_get_candles | ingest/market.py → kapanış bayraklı mum ve grafik | Uygulandı; prod mumları yeni UI'da okundu |
| market_get_trades | ingest/market.py → flow, gap/tazelik kontrolleri | Uygulandı; prod trade/decision kayıtları mevcut |
| market_get_orderbook | ingest/market.py → defter arşivi ve spread | Uygulandı; eski snapshot yeni UI'da güncel gösterilmez |
| account_get_balance, account_get_trade_fee | worker.py → özsermaye ve maliyet | Uygulandı; tarihsel doğrulama README'de; yeni ürün testinde hesap sorgusu yapılmadı |
| spot_place_order, spot_get_order, spot_get_fills | execution/venue.py → emir/fill yaşam döngüsü | Paper fixture testleri mevcut; 12 Eylül 12:11 SOL fill'i prod ledger'da görüldü; tek fill bütün hata senaryolarını doğrulamaz |
| spot_place_algo_order, spot_get_algo_orders | execution/venue.py → koruma / mutabakat | Uygulandı; paper fixture testleri mevcut; bu teslim yeni borsa yazma çağrısı yapmadı |
| Diğer allowlist araçları | atk/client.py | İzin verilmiş olması kullanıldığını veya doğrulandığını kanıtlamaz |

ATK ile alınan veri PostgreSQL'de kalır; ürünün `get_market_overview`,
`get_strategy`, `explain_wait` ve `get_risk_summary` araçları bu store'u okur.
Bunlar OKX araç adları değildir. Sohbet her cevapta borsaya gittiği iddiasını taşımaz.

Eksik: çağrı başına süre/sonuç/UNKNOWN, ortam ve schema hash'inin kalıcı izi;
endpoint eşlemesinin paket kaynağından tam matrisi; redakte edilmiş trace UI'sı.
Ham hassas yanıt veya imza bu rapora taşınmadı. Genel borsa public veri erişimi,
Trade/withdrawal izin doğrulaması olarak gösterilmez.
