# Capture guide: help decode the GS5's EQ and SuperWide commands

**Български — по-долу.**

Creative has not published how Creative App changes the EQ and SuperWide on the Sound Blaster GS5. We can learn it
by recording the USB messages the app sends while you click its buttons. It takes about 15 minutes, needs Windows,
and does not change anything on your PC or soundbar.

## What you need

- Windows PC with the GS5 connected by **USB-C**
- Creative App (the version you normally use)
- [Wireshark](https://www.wireshark.org/download.html): during setup, **tick "Install USBPcap"**, then restart the PC
- this tool installed (`gs5 --version` works)

## Steps

1. **Quit Creative App completely** (tray icon → Exit) and stop `gs5 run` if it is running.
2. Open **Wireshark**. In the interface list you will see `USBPcap1`, `USBPcap2`, … Click the ⚙ next to each one:
   pick the one that lists **Sound Blaster GS5** under its devices. (Not sure? Select all USBPcap entries with Ctrl.)
3. Start the capture (blue shark fin).
4. Open **Creative App**, choose the GS5 and wait **10 seconds** without touching anything.
5. Now do each of these actions, waiting **5 seconds** after each one, and write the order down in a text file
   (`notes.txt`):
   1. click every **EQ preset** from top to bottom (write the names exactly as the app shows them)
   2. turn **SuperWide on**, then **off**
   3. on the custom EQ, drag **the lowest band to maximum**, then **back to 0**; then the same for **the highest band**
   4. any other setting you would like a profile to control (dialog/voice, night mode, …), on then off
6. Stop the capture (red square) and **File → Save As…** `gs5-capture.pcapng`.
7. Decode it:

   ```
   gs5 decode-capture gs5-capture.pcapng --replies
   ```

   Each **burst** is one of your actions, in order. Match them with `notes.txt`.
8. Open an issue at https://github.com/esmobg/soundbar-autoprofile/issues with the decoder output and `notes.txt`.

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
      - "05 6a .. .. .. .."   # burst 3 = "Music" preset
```

and test it with `gs5 set music`. You can also try one frame with `gs5 send 05 6a ...`.

---

# Ръководство: запис на USB трафика, за да разгадаем EQ и SuperWide

Creative не публикува как Creative App сменя еквалайзера и SuperWide на GS5. Можем да го разберем, като запишем
USB съобщенията, които приложението праща, докато натискаш бутоните му. Отнема ~15 минути, трябва ти Windows и
нищо не се променя по компютъра или саундбара.

## Нужно е

- Windows компютър, GS5 свързан с **USB-C**
- Creative App
- [Wireshark](https://www.wireshark.org/download.html): при инсталацията **отметни „Install USBPcap“** и рестартирай
- този инструмент (`gs5 --version` работи)

## Стъпки

1. **Затвори Creative App напълно** (иконата до часовника → Exit) и спри `gs5 run`, ако върви.
2. Отвори **Wireshark**. В списъка има `USBPcap1`, `USBPcap2`, … Натисни ⚙ до всеки и избери този, под който се вижда
   **Sound Blaster GS5**. (Ако не си сигурен — маркирай всички USBPcap с Ctrl.)
3. Пусни записа (синята перка).
4. Отвори **Creative App**, избери GS5 и изчакай **10 секунди**, без да пипаш.
5. Направи следните действия, с **5 секунди** пауза след всяко, и запиши реда им в `notes.txt`:
   1. натисни всеки **EQ пресет** отгоре надолу (запиши имената точно както са в приложението)
   2. включи **SuperWide**, после го изключи
   3. в ръчния EQ дръпни **най-ниската лента до максимум**, после **обратно на 0**; същото за **най-високата**
   4. всяка друга настройка, която искаш профилите да сменят (глас/диалог, нощен режим, …) — вкл., после изкл.
6. Спри записа (червения квадрат) и **File → Save As…** `gs5-capture.pcapng`.
7. Декодирай:

   ```
   gs5 decode-capture gs5-capture.pcapng --replies
   ```

   Всеки **burst** е едно твое действие, по ред. Сравни ги с `notes.txt`.
8. Изпрати резултата и `notes.txt` (issue в GitHub или директно на мен).

> **Поверителност:** споделяй *резултата от декодера*, не самия `.pcapng`. Суровият запис съдържа всички устройства
> на този USB контролер — ако клавиатурата е на него, вътре е и това, което си писал по време на записа. Декодерът
> оставя само съобщенията на саундбара. Не пиши пароли, докато записваш.
