# Troubleshooting

**Български — по-долу.**

Start here: `gs5 probe` checks the soundbar, `gs5 detect --watch` shows what the tool sees and which profile the
rules pick. Most problems show up in one of the two.

## The soundbar is not found

`gs5 probe` says `no Sound Blaster GS5 found` or similar.

- **Use the USB-C cable.** Settings can only be changed over USB. Bluetooth, optical and AUX carry audio only, so
  a soundbar connected just by Bluetooth is invisible to this tool.
- **The cable must carry data.** Many USB-C cables (especially those that came with phones or power banks) are
  charge-only. If Windows does not show "Sound Blaster GS5" under *Sound* or *Device Manager*, try another cable.
- Plug it straight into the computer rather than through an unpowered hub or a monitor's USB port.
- Run `gs5 probe` again. It is read-only and safe to repeat.
- On Linux, see the next section.

## Linux: permission denied

Without a udev rule only root can open the soundbar's HID interface. Install the rule shipped in the repository
(it is also attached to each release), then **unplug and replug** the USB cable:

```bash
sudo cp udev/70-gs5-hidraw.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
```

The rule gives the logged-in user access to `hidraw` devices with USB ID `041e:329d`. If it still fails, check
that your distribution uses systemd-logind (the `uaccess` tag depends on it); otherwise add yourself to a group and
change the rule to `GROUP="<group>"`.

## The sound does not change (Windows)

EQ, SuperWide and the other effects are switched by picking a Sound Mode in Creative App (`sound_mode:` in the
profile). The log or `gs5 set <profile>` says why it did not work:

- `needs the 'uiautomation' package`: it is installed with the tool on Windows; if it is missing, run
  `pip install uiautomation` in the same environment.
- `Creative App not found at …`: install Creative App. It must stay installed.
- `Creative App did not open its window in time`: the first switch starts the app minimized and can take about
  15 seconds, longer on a slow PC. Try again once it is open.
- `no sound mode 'X' in Creative App`: the name does not match. `gs5 modes` lists all modes; use the name exactly as
  the app shows it (any case), its internal name (e.g. `Movie`) or its id.
- `Creative App shows no Sound Mode list`: open Creative App once, make sure the GS5 is connected and selected
  there, then try again.
- `eq 'music': the GS5 has no USB command for EQ presets`: your config still uses `eq:` / `superwide:`. On the
  GS5 replace them with `sound_mode:` (see `gs5 config show` for the current default).
- On **macOS and Linux** `sound_mode` is skipped with a warning: Creative App and Creative's processing only exist
  on Windows. The lighting still changes.

## The Sound Mode changes back

Creative App may stay open, minimized or in the background; it is needed for Sound Modes. But do **not** change
the Sound Mode in Creative App by hand while automatic switching runs: the next profile switch overrides it. To
keep one profile for a while, pick it in the tray menu (choose **Automatic** to go back to the rules) or choose
**Pause**.

## The profile flips back and forth

- `hold_seconds` (default 3): how long a new profile must stay chosen before it is applied. Raise it to 5–10 if a
  quick alt-tab or a short notification sound switches the profile.
- `media_grace_seconds` (default 15): pausing or skipping a track counts as still playing for this long. Raise it
  if the soundbar switches away while you pick the next song.
- Run `gs5 detect --watch` while it happens. The `profile=… (reason)` line names the rule that matched, so you can
  see which rule is too broad and add an `unless:` to it.

Both settings are at the top of the config file (`gs5 config path`). Check it with `gs5 config check`.

## The browser (or anything) is not detected

What can be seen depends on the operating system:

- **Windows:** media from any player or browser that shows up in the volume flyout, the focused app, full screen
  (also exclusive full-screen games) and microphone use. App names are shown cleaned up, e.g. `Firefox`,
  `Spotify`; `gs5 detect --watch` shows the exact names to use in rules.
- **macOS:** since macOS 15.4 Apple no longer lets other programs read the system "Now Playing" information.
  Install [`media-control`](https://github.com/ungive/media-control) (`brew install media-control`), which still
  works and sees browsers too. Without it only Spotify and Music are read. Full screen needs
  `pyobjc-framework-Quartz`; the microphone is not detected on macOS.
- **Linux on X11:** install `playerctl`, `xdotool`, `xprop` and `pactl` (part of the PulseAudio/PipeWire tools).
- **Linux on Wayland:** Wayland does not tell other programs which window is focused. Hyprland (`hyprctl`) and sway
  (`swaymsg`) are supported, KDE Plasma through [`kdotool`](https://github.com/jinliu/kdotool) (no full-screen
  information). On GNOME and other compositors `foreground_app`, `foreground_title` and `fullscreen` stay empty,
  but media rules still work: Firefox and Chromium publish what they play over MPRIS, so `media_title` rules catch
  most browser video.

## Reading the log

The recommended way to run it every day is `gs5 tray` (a tray icon), started at login by `gs5 autostart install`.
The tray always writes a log file; `gs5 run` writes one with `--log-file`. The tray menu's **Open log folder**
opens it, or:

```bash
gs5 config path            # the log, soundbar-autoprofile.log, is in the same folder
gs5 run --log-file -v      # run in the terminal with debug messages, also written to that file
```

Typical lines:

- `profile -> movie  (video player or streaming service; app=vlc media=VLC)`: a switch, and the rule that caused it.
- `sound_mode: …`: the Sound Mode could not be switched, see above.
- `lost the soundbar: …`, then `… (retrying every 5 s)`: the cable was unplugged or the soundbar went to sleep. It
  reconnects by itself and re-applies the right profile.

Attach the relevant lines when you open a bug report. Remove track or window titles you do not want to share.

## The light strip goes dark

The GS5 turns its lights off on standby and does not always turn them back on. The tool re-sends the lighting every
`keepalive_seconds` (default 120). Lower it (for example to 30) if the strip stays dark too long after the
soundbar wakes up, or set `0` to turn the keepalive off.

---

# Отстраняване на проблеми

Започни оттук: `gs5 probe` проверява саундбара, а `gs5 detect --watch` показва какво вижда инструментът и кой
профил избират правилата. Повечето проблеми личат в една от двете команди.

## Саундбарът не се намира

`gs5 probe` казва `no Sound Blaster GS5 found` или нещо подобно.

- **Свържи го с USB-C кабела.** Настройките се сменят само през USB. Bluetooth, оптиката и AUX пренасят само звук,
  така че саундбар, свързан само по Bluetooth, е невидим за инструмента.
- **Кабелът трябва да пренася данни.** Много USB-C кабели (особено от телефони и външни батерии) са само за
  зареждане. Ако Windows не показва „Sound Blaster GS5“ в *Звук* или *Диспечер на устройствата*, пробвай друг кабел.
- Включи го директно в компютъра, а не през хъб без захранване или USB порта на монитора.
- Пусни `gs5 probe` пак. Командата само чете и може да се повтаря спокойно.
- На Linux виж следващата точка.

## Linux: нямаш права (permission denied)

Без udev правило само root може да отвори HID интерфейса на саундбара. Инсталирай правилото от хранилището (то е
приложено и към всяко издание в Releases) и после **извади и включи пак** USB кабела:

```bash
sudo cp udev/70-gs5-hidraw.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
```

Правилото дава достъп на влезлия потребител до `hidraw` устройства с USB ID `041e:329d`. Ако пак не става, провери
дали дистрибуцията ти ползва systemd-logind (етикетът `uaccess` зависи от него). Ако не, добави се в група и смени
правилото на `GROUP="<група>"`.

## Звукът не се сменя (Windows)

Еквалайзерът, SuperWide и другите ефекти се сменят, като се избере звуков режим (Sound Mode) в Creative App
(`sound_mode:` в профила). Логът или `gs5 set <профил>` казват защо не е станало:

- `needs the 'uiautomation' package`: под Windows се инсталира заедно с инструмента; ако липсва, пусни
  `pip install uiautomation` в същата среда.
- `Creative App not found at …`: инсталирай Creative App. Тя трябва да остане инсталирана.
- `Creative App did not open its window in time`: първата смяна пуска приложението минимизирано и може да отнеме
  около 15 секунди, на бавен компютър и повече. Опитай пак, след като се отвори.
- `no sound mode 'X' in Creative App`: името не съвпада. `gs5 modes` изрежда всички режими; пиши името точно както
  е в приложението (малки и главни букви нямат значение), вътрешното име (например `Movie`) или id-то.
- `Creative App shows no Sound Mode list`: отвори Creative App веднъж, увери се, че GS5 е свързан и избран там, и
  опитай пак.
- `eq 'music': the GS5 has no USB command for EQ presets`: конфигурацията ти още ползва `eq:` / `superwide:`. За GS5
  ги замени със `sound_mode:` (`gs5 config show` показва текущата конфигурация по подразбиране).
- На **macOS и Linux** `sound_mode` се пропуска с предупреждение: Creative App и обработката на Creative съществуват
  само под Windows. Осветлението се сменя нормално.

## Звуковият режим се връща

Creative App може да стои отворена, минимизирана или във фонов режим: тя е нужна за звуковите режими. Но **не**
сменяй звуковия режим в нея на ръка, докато върви автоматичната смяна: следващата смяна на профил ще го презапише.
Ако искаш един профил за известно време, избери го от менюто в трея (**Automatic** връща правилата) или натисни
**Pause**.

## Профилът се сменя напред-назад

- `hold_seconds` (по подразбиране 3): колко време новият профил трябва да остане избран, преди да се приложи.
  Вдигни го на 5–10, ако бърз alt-tab или кратък звук от известие сменя профила.
- `media_grace_seconds` (по подразбиране 15): пауза или следваща песен се броят за „още свири“ толкова време.
  Вдигни го, ако саундбарът превключва, докато избираш следващата песен.
- Пусни `gs5 detect --watch`, докато се случва. Редът `profile=… (причина)` казва кое правило е съвпаднало, така
  виждаш кое е твърде широко и можеш да му добавиш `unless:`.

Двете настройки са най-горе в конфигурационния файл (`gs5 config path`). Провери го с `gs5 config check`.

## Браузърът (или нещо друго) не се разпознава

Какво се вижда зависи от операционната система:

- **Windows:** медия от всеки плейър или браузър, който се появява в панела за звука, активното приложение, цял
  екран (и игри в exclusive full screen) и микрофонът. Имената на приложенията се изчистват, например `Firefox`,
  `Spotify`; `gs5 detect --watch` показва точните имена, които да ползваш в правилата.
- **macOS:** от macOS 15.4 Apple не позволява на други програми да четат системното „Now Playing“. Инсталирай
  [`media-control`](https://github.com/ungive/media-control) (`brew install media-control`): то продължава да
  работи и вижда и браузърите. Без него се четат само Spotify и Music. За цял екран трябва
  `pyobjc-framework-Quartz`; микрофонът на macOS не се засича.
- **Linux с X11:** инсталирай `playerctl`, `xdotool`, `xprop` и `pactl` (от инструментите на PulseAudio/PipeWire).
- **Linux с Wayland:** Wayland не казва на другите програми кой прозорец е активен. Поддържат се Hyprland
  (`hyprctl`) и sway (`swaymsg`), а KDE Plasma — чрез [`kdotool`](https://github.com/jinliu/kdotool) (без данни за
  цял екран). На GNOME и други среди `foreground_app`, `foreground_title` и `fullscreen` остават празни, но правилата
  за медия работят: Firefox и Chromium обявяват какво пускат през MPRIS и правилата с `media_title` хващат повечето
  видеа в браузъра.

## Как да четеш лога

За всекидневна употреба препоръчваме `gs5 tray` (икона в трея), а `gs5 autostart install` я пуска при влизане в
системата. Иконата винаги пише лог; `gs5 run` пише лог с `--log-file`. Отваря се от **Open log folder** в менюто на
иконата или така:

```bash
gs5 config path            # логът, soundbar-autoprofile.log, е в същата папка
gs5 run --log-file -v      # пуска го в терминала с подробни съобщения, записани и във файла
```

Често срещани редове:

- `profile -> movie  (video player or streaming service; app=vlc media=VLC)`: смяна на профил и правилото, което я е
  предизвикало.
- `sound_mode: …`: звуковият режим не е сменен, виж по-горе.
- `lost the soundbar: …`, после `… (retrying every 5 s)`: кабелът е изваден или саундбарът е заспал. Свързва се
  отново сам и прилага правилния профил.

Когато пускаш bug report, добави съответните редове. Махни заглавията на песни или прозорци, които не искаш да
споделяш.

## Светлините угасват

GS5 гаси светлините в режим на готовност и не винаги ги пуска отново. Инструментът праща осветлението наново на
всеки `keepalive_seconds` (по подразбиране 120). Намали го (например на 30), ако лентата стои тъмна твърде дълго,
след като саундбарът се събуди, или сложи `0`, за да го изключиш.
