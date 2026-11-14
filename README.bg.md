# soundbar-autoprofile

**Саундбарът сам сменя звуковия си профил: музика → Music, филм → Movies, работа/разговор → Effects Off,
игра → Gaming.** Започва с Creative Sound Blaster GS5 и е направен така, че да се добавят и други саундбари.

[English](README.md)

Инструментът следи какво се пуска (Spotify, VLC, Netflix, YouTube…), кое приложение е отпред, дали е на цял екран и
дали се ползва микрофонът. После избира профил по твоите правила и го прилага: **звуковия режим (Sound Mode)** в
Creative App (EQ, SuperWide, Crystalizer, Bass, Smart Volume, Dialog+) и **светлинната лента** през USB.

## Какво работи

| Функция (Sound Blaster GS5) | Windows | macOS / Linux |
|---|---|---|
| Звуков режим за всеки профил (EQ, SuperWide, ефекти) | ✅ чрез Creative App | ❌ там няма Creative App |
| Твои собствени режими, създадени в Creative App | ✅ | ❌ |
| RGB цвят / яркост за всеки профил | ✅ | ✅ |

При GS5 еквалайзерът, SuperWide и другите ефекти не се пазят в саундбара: прилага ги аудио драйверът на Creative на
самия компютър, а Creative App го настройва. На macOS и Linux саундбарът свири без тази обработка, затова там се
сменя само осветлението. Подробности: [docs/PROTOCOL.md](docs/PROTOCOL.md).

| Платформа | Какво се разпознава | Състояние |
|---|---|---|
| Windows 10/11 | медия от всеки плейър и браузър, активно приложение, цял екран (и игри в exclusive full screen), микрофон | ✅ тествано |
| macOS | медия от всяко приложение с [`media-control`](https://github.com/ungive/media-control) (иначе само Spotify/Music), активно приложение, цял екран; без микрофон | ⚠️ нетествано на хардуер |
| Linux (X11) | MPRIS плейъри и видео (`playerctl`), активно приложение и цял екран (`xdotool`, `xprop`), микрофон (`pactl`) | ⚠️ нетествано на хардуер |
| Linux (Wayland) | като X11 на Hyprland и sway; KDE чрез `kdotool` (без цял екран); GNOME: само медия и микрофон | ⚠️ нетествано на хардуер |
| Android | планирано: приложение през Bluetooth, виж [docs/MOBILE.md](docs/MOBILE.md) | 🗺️ |
| iOS | невъзможно: iOS не позволява на приложение да следи другите приложения и да управлява саундбара във фонов режим | ❌ |

Свържи саундбара с **USB-C кабела**: осветлението се управлява през USB, а под Windows обработката на звука от
Creative е част от USB аудио драйвера ѝ. През Bluetooth, оптика или AUX нищо не може да се сменя.

## Инсталация

**Windows, най-лесно:** изтегли `soundbar-autoprofile-windows-x64.exe` от
[Releases](https://github.com/esmobg/soundbar-autoprofile/releases) и го пусни. Появява се икона в системния трей.
Същият файл приема и всички `gs5` команди, например `soundbar-autoprofile-windows-x64.exe probe`. Там има и версии
за macOS (`…-macos-arm64.zip`) и Linux (`…-linux-x64`), засега експериментални.

**С Python** 3.10 или по-нов:

```bash
pipx install "soundbar-autoprofile[tray] @ git+https://github.com/esmobg/soundbar-autoprofile"
```

(или същото с `pip install`; махни `[tray]`, ако не искаш икона в трея)

- **Windows:** инсталирай Creative App от сайта за поддръжка на Creative и не я деинсталирай: звуковите режими се
  сменят чрез нея.
- **Linux:** копирай `udev/70-gs5-hidraw.rules` в `/etc/udev/rules.d/` (цялата команда е в README.md), извади и
  включи пак кабела, и инсталирай `playerctl`, а на X11 и `xdotool` и `xprop`.
- **macOS:** `brew install media-control`, за да вижда какво пускат браузърите и другите приложения, и
  `pip install pyobjc-framework-Quartz` (в същата среда), за да разпознава цял екран. При първото пускане може да
  поиска разрешение да управлява Spotify/Music (Automation).

## Бърз старт

```bash
gs5 probe                  # вижда ли се саундбарът?
gs5 detect --watch         # какво се разпознава и кой профил избират правилата
gs5 set movie              # приложи профил веднага
gs5 tray                   # автоматична смяна с икона в трея (препоръчително)
gs5 autostart install      # пуска иконата при влизане в системата (без администраторски права)
```

Менюто на иконата показва активния профил и позволява да избереш профил на ръка (**Automatic** връща правилата),
**Pause**, отваряне на настройките и папката с лога, както и **Start at login**. Без допълнението `[tray]`
`gs5 run` прави същото в терминала, а `gs5 autostart install --no-tray` го пуска при влизане.

**Creative App:** остави я инсталирана. Може да стои минимизирана или във фонов режим. Ако не е пусната, се
стартира минимизирана, когато трябва да се смени звуковият режим (около 15 с първия път, около 2 с при всяка
следваща смяна). Не сменяй звуковия режим в Creative App на ръка, докато върви автоматичната смяна: следващото
превключване ще го презапише. Вместо това избери профил от менюто в трея.

## Настройки

`gs5 config init` създава конфигурационния файл, `gs5 config path` показва къде е, а `gs5 config check` го
проверява. Профилите казват **какво** да се сложи (`sound_mode`, `rgb`, `brightness`). Правилата казват **кога**:
проверяват се отгоре надолу и печели първото, което съвпадне:

```yaml
profiles:
  music:  { sound_mode: Music,  rgb: "8a2be2", brightness: 70 }
  movie:  { sound_mode: "Филми и видео", rgb: "ff5a00", brightness: 30 }   # свой режим от Creative App

rules:
  - profile: movie
    when: { media_playing: true, media_app: "vlc|netflix|plex" }
  - profile: music
    when: { media_playing: true }
```

Полетата за правилата и останалите настройки (`hold_seconds`, `media_grace_seconds`) са описани в README.md.

`sound_mode` е който и да е звуков режим от Creative App: фабричен (Effects Off, Music, Movies, Gaming, Bass Boost,
Treble Boost, Dynamic Music, Esports, FPS, RPG и много режими за конкретни игри) или **твой собствен**, в който
можеш да събереш какъвто искаш EQ, SuperWide и ефекти. Пиши името така, както е в приложението, включително на
български (например „Филми и видео“); малки и главни букви нямат значение. `gs5 modes` ги изрежда.

Ако нещо не работи: [Отстраняване на проблеми](docs/TROUBLESHOOTING.md). Въпроси: [ЧЗВ](docs/FAQ.md).

## Лиценз

MIT. Протоколът за светлините е от [JRiley2025/gs5-rgb](https://github.com/JRiley2025/gs5-rgb) (MIT). Проектът не е
свързан с Creative Technology Ltd.
