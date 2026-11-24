> 🚧 **Durum: aktif geliştirme.** Yazarın kullanımında çalışıyor; arayüzler değişebilir.

# first-issue-radar (Açık Kaynak Radarı)

[English README](README.md)

GitHub'da ilk katkı için uygun, açık ve kimseye atanmamış işleri (`good first issue`, `first-timers-only`, `documentation` + `help wanted`) arayan küçük yerel web uygulaması. Birini seçersiniz; sonra güncel ayrıntıları kontrol eder: açıklama, sınırlı sayıda yorum, ilgili açık PR'lar, katkı kuralları konumu ve lisans. Yalnız okur: issue ya da PR oluşturmaz, yorum yazmaz, listelenen projelerin kodunu indirmez veya çalıştırmaz.

## Hızlı başlangıç

Gereksinim: **Windows** (tek örnek kilidi `msvcrt` kullanır), Python 3 (yalnız standart kütüphane; 3.12 ile geliştirildi) ve `gh auth login` ile oturum açılmış [GitHub CLI](https://cli.github.com/) (`gh`).

```bat
baslat.cmd
```

ya da bu klasörde terminalden:

```sh
python -B -X utf8 server.py
```

Uygulama tarayıcıyı `127.0.0.1` üzerinde rastgele bir portta açar; pencere açık kaldığı sürece çalışır (durdurmak için o pencerede Ctrl+C). Seçiminiz `data/radar.sqlite` içinde saklanır.

## İsteğe bağlı yapılandırma

Yan panel, kendi bir PR'ınızı izleyebilir (durum, kontroller, profil katkı grafiğinde görünürlük). `config.example.json` dosyasını `config.json` olarak kopyalayıp düzenleyin ya da ortam değişkenlerini kullanın (dosyadan önceliklidir):

| Ayar | Ortam değişkeni | Anlamı |
|---|---|---|
| `github_login` | `RADAR_GITHUB_LOGIN` | İsteğe bağlı. Verilirse `gh` hesabı bununla eşleşmelidir; eşleşmezse hesap güvenilmez sayılır. |
| `tracked_pr` | `RADAR_TRACKED_PR` | İsteğe bağlı. `owner/repo#numara`. Yoksa yan panel PR tanımlı olmadığını söyler. |

## Testler

```sh
python -X utf8 -m unittest -v test_radar
```

25 test; 24'ü GitHub çağrıları taklit edilerek çevrimdışı koşar, 1 canlı test varsayılanda atlanır. Canlı salt okunur test `gh` oturumu ve ağ ister: `RADAR_LIVE=1 python -X utf8 -m unittest -v test_radar.Live` (Git Bash).

## Güvenlik notları

- Sunucu yalnız `127.0.0.1` dinler; `Host` ve `Origin` başlıklarını denetler, POST için çalıştırma başına token ister, istek boyutunu sınırlar. Token tarayıcıdan gelen siteler arası isteklere karşıdır; aynı bilgisayarda sizin adınıza çalışan diğer programlara karşı **güvenlik sınırı değildir**.
- Yalnız sabit, salt okunur GitHub yollarına izin verilir; tek GraphQL sorgusu sabittir.
- `gh` oturumu ve yetkileri değiştirilmez.

## Sınırlar ve doğrulanmamış iddialar

- Tarama, üç sınırlı arama yapar (her biri 20 sonuç); tüm fırsatları kapsamaz. GitHub eksik sonuç bildirirse sonuç "kısmi" işaretlenir.
- Puanlama ve efor tahmini henüz yok; sonuçlar "Puanlanmadı" gösterilir.
- Projenin yapay zekâ/katkı politikası **analiz edilmez**; bilinmiyor gösterilir.
- İzlenen PR'ın profilde görünürlüğü, GitHub tam yanıt vermezse bilinmiyor kalır.
- Yalnız Windows; Windows'ta Python 3.12 ve `gh` 2.x ile denendi.

## Lisans

Apache-2.0, bkz. [LICENSE](LICENSE) ve [NOTICE](NOTICE).
