# FAQ

**Български — по-долу.**

### Does it change the sound quality? Is it safe for my soundbar?

It does not process audio itself. It only switches settings you could switch by hand: on Windows it picks a Sound
Mode in Creative App, exactly as if you clicked it, and over USB it sends the same lighting commands Creative App
sends. No firmware is changed. If you want everything back the way it was, stop the tool and choose the settings in
Creative App.

`gs5 probe` is read-only, and `gs5 set <profile> --dry-run` or `gs5 run --dry-run` show what would be applied
without applying it.

### Do I need Creative App?

On Windows, yes, for the sound: the GS5's EQ, SuperWide, Crystalizer, Bass, Smart Volume and Dialog+ are applied
by Creative's audio driver on the PC and configured through Creative App, so the tool switches them by choosing a
Sound Mode there. Keep it installed; it may stay minimized or in the background, and it is started minimized when
needed. Just do not change the Sound Mode by hand while automatic switching runs (use the tray menu instead). The
lighting works without Creative App on every OS.

### Can I use my own sound settings?

Yes. Make a Sound Mode in Creative App with the EQ, SuperWide and effects you like, then put its name in a profile:
`sound_mode: My Movie Night`. `gs5 modes` lists all modes the app has.

### Why does the EQ not change on macOS or Linux?

Because on the GS5 the EQ and effects are not inside the soundbar. Creative's Windows driver applies them to the
audio before it reaches the soundbar, and Creative App does not exist on macOS or Linux. There the soundbar plays
without that processing, and the tool can only change the lighting. See [PROTOCOL.md](PROTOCOL.md).

### The docs used to say the EQ was "not decoded yet". What changed?

We recorded the USB traffic while changing every audio setting in Creative App and found that none of it goes to
the soundbar. There is nothing to decode over USB; switching Sound Modes in Creative App is the way to do it.

### Does it work over Bluetooth?

No. The GS5 accepts settings only over its USB-C connection. Bluetooth, optical and AUX carry audio only, and
Creative's processing on Windows is part of its USB audio driver.

### What about other Creative soundbars (Katana, Stage, GS3, …)?

Not yet. The code is built for more than one device, but each model needs its own driver. If you own one,
[open a device support request](https://github.com/esmobg/soundbar-autoprofile/issues/new?template=device_request.yml),
ideally with a USB capture ([capture guide](CAPTURE_GUIDE.md)). Soundbars from other brands are welcome too.

### What does it know about me? Does it send anything anywhere?

It runs entirely on your computer. It reads what is playing, which app is in front, whether it is full screen and
whether the microphone is in use, only to pick a profile. It has no network code, no telemetry and no update check.
Nothing is stored apart from your config file and a local log file (`gs5 config path` shows the folder). The log
can contain app names and track or window titles, so read it before you share it.

### Does it work on my phone?

Not yet on Android, and it cannot work on iOS. See [MOBILE.md](MOBILE.md).

### How do I stop it?

Ctrl+C in the terminal, **Quit** in the tray menu, or **Pause** there to stop switching for a while.
`gs5 autostart uninstall` stops it starting at login.

---

# Често задавани въпроси

### Променя ли качеството на звука? Безопасно ли е за саундбара?

Самият инструмент не обработва звука. Той само превключва настройки, които можеш да смениш и на ръка: под Windows
избира звуков режим (Sound Mode) в Creative App, точно както ако го натиснеш ти, а по USB праща същите команди за
осветлението, които праща и Creative App. Фърмуерът не се пипа. Ако искаш всичко да е както преди, спри
инструмента и избери настройките в Creative App.

`gs5 probe` само чете, а `gs5 set <профил> --dry-run` и `gs5 run --dry-run` показват какво би се приложило, без да
го прилагат.

### Трябва ли ми Creative App?

Под Windows — да, за звука: еквалайзерът, SuperWide, Crystalizer, Bass, Smart Volume и Dialog+ на GS5 се прилагат
от аудио драйвера на Creative на компютъра и се настройват през Creative App, затова инструментът ги сменя, като
избира звуков режим там. Остави я инсталирана; може да стои минимизирана или във фонов режим, а когато трябва, се
пуска минимизирана. Само не сменяй звуковия режим на ръка, докато върви автоматичната смяна (ползвай менюто в
трея). Осветлението работи без Creative App на всяка система.

### Мога ли да ползвам свои настройки на звука?

Да. Създай звуков режим в Creative App с еквалайзера, SuperWide и ефектите, които харесваш, и сложи името му в
профил: `sound_mode: Моята кино вечер`. `gs5 modes` изрежда всички режими в приложението.

### Защо еквалайзерът не се сменя на macOS или Linux?

Защото при GS5 еквалайзерът и ефектите не са в самия саундбар. Драйверът на Creative за Windows ги прилага върху
звука, преди той да стигне до саундбара, а Creative App я няма за macOS и Linux. Там саундбарът свири без тази
обработка и инструментът може да сменя само осветлението. Виж [PROTOCOL.md](PROTOCOL.md).

### По-рано в документацията пишеше, че EQ „още не е разгадан“. Какво се промени?

Записахме USB трафика, докато сменяхме всяка звукова настройка в Creative App, и се оказа, че нищо от това не
стига до саундбара. По USB няма какво да се разгадава; правилният начин е смяната на звуковите режими в Creative App.

### Работи ли през Bluetooth?

Не. GS5 приема настройки само през USB-C. Bluetooth, оптиката и AUX пренасят само звук, а обработката на Creative
под Windows е част от USB аудио драйвера ѝ.

### А други саундбари на Creative (Katana, Stage, GS3, …)?

Още не. Кодът е направен за повече от едно устройство, но всеки модел има нужда от свой драйвер. Ако имаш такъв,
[пусни заявка за ново устройство](https://github.com/esmobg/soundbar-autoprofile/issues/new?template=device_request.yml),
най-добре с USB запис ([ръководството](CAPTURE_GUIDE.md)). Саундбари от други марки също са добре дошли.

### Какво знае за мен? Праща ли нещо някъде?

Работи изцяло на твоя компютър. Чете какво се пуска, кое приложение е отпред, дали е на цял екран и дали се ползва
микрофонът, само за да избере профил. Няма мрежов код, телеметрия или проверка за обновления. Не пази нищо освен
конфигурационния файл и локален лог (`gs5 config path` показва папката). В лога може да има имена на приложения и
заглавия на песни или прозорци, затова го прегледай, преди да го споделиш.

### Работи ли на телефон?

На Android още не, а на iOS не може. Виж [MOBILE.md](MOBILE.md) (кратко резюме на български има най-долу).

### Как да го спра?

Ctrl+C в терминала, **Quit** в менюто в трея или **Pause** там, за да спре смяната за известно време.
`gs5 autostart uninstall` спира пускането при влизане в системата.
