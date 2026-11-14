# Capture guide: record what a soundbar's app sends over USB

**Български — по-долу.**

Manufacturers rarely publish how their app talks to a soundbar. We can learn it by recording the USB messages the
app sends while you click its buttons. It takes about 15 minutes, needs Windows, and does not change anything on
your PC or soundbar.

**Sound Blaster GS5 owners:** you do not need this for the EQ. On the GS5, EQ, SuperWide and the other effects are
not sent over USB at all; Creative's driver applies them on the PC, and soundbar-autoprofile switches them through
Creative App's Sound Modes (see [PROTOCOL.md](PROTOCOL.md)). A GS5 capture is still useful after a firmware or
Creative App update, in case this changes.

Captures are most useful for:

- **other soundbars** (Creative Katana, Stage, GS3, other brands): this is how a new driver starts;
- **new GS5 firmware or Creative App versions**;
- the **Bluetooth** link, which needs a different recording on Android: see [MOBILE.md](MOBILE.md).

## What you need

- Windows PC with the soundbar connected by **USB**
- the manufacturer's app (for Creative: Creative App, the version you normally use)
- [Wireshark](https://www.wireshark.org/download.html): during setup, **tick "Install USBPcap"**, then restart the PC
- this tool installed (`gs5 --version` works)

## Steps

1. **Quit the manufacturer's app completely** (tray icon → Exit) and stop `gs5 tray` / `gs5 run` if it is running.
2. Open **Wireshark**. In the interface list you will see `USBPcap1`, `USBPcap2`, … Click the ⚙ next to each one:
   pick the one that lists **your soundbar** under its devices. (Not sure? Select all USBPcap entries with Ctrl.)
3. Start the capture (blue shark fin).
4. Open the app, choose the soundbar and wait **10 seconds** without touching anything.
5. Now do each of these actions, waiting **5 seconds** after each one, and write the order down in a text file
   (`notes.txt`):
   1. click every **EQ preset or sound mode** from top to bottom (write the names exactly as the app shows them)
   2. turn **surround / virtual sound** (SuperWide on Creative) **on**, then **off**
   3. change the **lighting** colour and brightness, if it has lighting
   4. any other setting you would like a profile to control (dialog/voice, night mode, …), on then off
6. Stop the capture (red square) and **File → Save As…** `capture.pcapng`.
7. Decode it:

   ```
   gs5 decode-capture capture.pcapng --replies
   ```

   Each **burst** is one of your actions, in order. Match them with `notes.txt`. If the decoder finds no frames,
   the device may use a different report format: say so in the issue, and we will look at it together.
8. Open a [decoded command submission](https://github.com/esmobg/soundbar-autoprofile/issues/new?template=decoded_command.yml)
   with the decoder output and `notes.txt` (for a soundbar we do not support yet, use a
   [device support request](https://github.com/esmobg/soundbar-autoprofile/issues/new?template=device_request.yml)).

On a GS5 you can also run `gs5 listen` while you click through Creative App: it prints everything the soundbar
sends, without sending anything itself.

> **Privacy:** share the *decoder output*, not the raw `.pcapng`. A raw USB capture records every device on that USB
> controller — if your keyboard is on the same one, it contains what you typed during the capture. The decoder only
> keeps Creative soundbar frames. Avoid typing passwords while capturing.

## Using the commands right away

You do not have to wait for a new release: put the frames of a burst into a profile's `frames:` list in your config
(`gs5 config path`), for example

```yaml
profiles:
  music:
    frames:
      - "05 6a .. .. .. .."   # burst 3
```

and test it with `gs5 set music`. You can also try one frame with `gs5 send 05 6a ...`.

---

# Ръководство: запис на това, което приложението на саундбара праща по USB

Производителите рядко публикуват как приложението им говори със саундбара. Можем да го разберем, като запишем USB
съобщенията, които приложението праща, докато натискаш бутоните му. Отнема ~15 минути, трябва ти Windows и нищо не
се променя по компютъра или саундбара.

**Ако имаш Sound Blaster GS5:** за EQ това не ти трябва. При GS5 еквалайзерът, SuperWide и другите ефекти изобщо не
се пращат по USB: прилага ги драйверът на Creative на компютъра, а soundbar-autoprofile ги сменя чрез звуковите
режими (Sound Modes) в Creative App (виж [PROTOCOL.md](PROTOCOL.md)). Запис от GS5 все пак е полезен след ново
фърмуерно обновление или нова версия на Creative App, в случай че нещо се промени.

Записите са най-полезни за:

- **други саундбари** (Creative Katana, Stage, GS3, други марки): така започва нов драйвер;
- **нов фърмуер на GS5 или нова версия на Creative App**;
- връзката по **Bluetooth**, за която се прави друг запис на Android: виж [MOBILE.md](MOBILE.md).

## Нужно е

- Windows компютър, саундбарът свързан с **USB**
- приложението на производителя (за Creative: Creative App)
- [Wireshark](https://www.wireshark.org/download.html): при инсталацията **отметни „Install USBPcap“** и рестартирай
- този инструмент (`gs5 --version` работи)

## Стъпки

1. **Затвори приложението на производителя напълно** (иконата до часовника → Exit) и спри `gs5 tray` / `gs5 run`,
   ако вървят.
2. Отвори **Wireshark**. В списъка има `USBPcap1`, `USBPcap2`, … Натисни ⚙ до всеки и избери този, под който се вижда
   **твоят саундбар**. (Ако не си сигурен — маркирай всички USBPcap с Ctrl.)
3. Пусни записа (синята перка).
4. Отвори приложението, избери саундбара и изчакай **10 секунди**, без да пипаш.
5. Направи следните действия, с **5 секунди** пауза след всяко, и запиши реда им в `notes.txt`:
   1. натисни всеки **EQ пресет или звуков режим** отгоре надолу (запиши имената точно както са в приложението)
   2. включи **съраунд / виртуален звук** (SuperWide при Creative), после го изключи
   3. смени **цвета и яркостта** на осветлението, ако има такова
   4. всяка друга настройка, която искаш профилите да сменят (глас/диалог, нощен режим, …) — вкл., после изкл.
6. Спри записа (червения квадрат) и **File → Save As…** `capture.pcapng`.
7. Декодирай:

   ```
   gs5 decode-capture capture.pcapng --replies
   ```

   Всеки **burst** е едно твое действие, по ред. Сравни ги с `notes.txt`. Ако декодерът не намери нищо,
   устройството може да ползва друг формат: напиши го в issue-то и ще го разгледаме заедно.
8. Пусни [decoded command submission](https://github.com/esmobg/soundbar-autoprofile/issues/new?template=decoded_command.yml)
   с резултата и `notes.txt` (за саундбар, който още не се поддържа, ползвай
   [заявка за ново устройство](https://github.com/esmobg/soundbar-autoprofile/issues/new?template=device_request.yml)).
   Може да пишеш на български.

С GS5 можеш да пуснеш и `gs5 listen`, докато цъкаш в Creative App: показва всичко, което саундбарът праща, без
самата команда да праща нещо.

> **Поверителност:** споделяй *резултата от декодера*, не самия `.pcapng`. Суровият запис съдържа всички устройства
> на този USB контролер — ако клавиатурата е на него, вътре е и това, което си писал по време на записа. Декодерът
> оставя само съобщенията на саундбара. Не пиши пароли, докато записваш.
