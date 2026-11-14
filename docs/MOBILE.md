# Phones: Android and iOS

**Български — накратко най-долу.**

soundbar-autoprofile runs on a computer connected to the soundbar by USB-C. People often ask for the same thing on
a phone. Short answer: **Android is feasible later, iOS is not.** This page explains why and what would be needed.

A phone version needs two things the desktop version already has:

1. **Know what is playing** (and ideally whether a call is going on).
2. **Send settings to the soundbar** without USB, so over Bluetooth.

## Android: feasible, once the Bluetooth protocol is known

### 1. Knowing what plays: solved by public APIs

- A `NotificationListenerService`, once the user enables it under *Settings → Notification access*, may call
  `MediaSessionManager.getActiveSessions()`. That returns a `MediaController` for every app that plays media
  (Spotify, YouTube, Netflix, browsers, podcasts), with its package name, play state and title/artist metadata, and
  callbacks when they change. This is the same kind of information the Windows version reads.
- Calls and meetings: `AudioManager.getMode()` (`MODE_IN_CALL`, `MODE_IN_COMMUNICATION`) and
  `AudioManager.getActiveRecordingConfigurations()` show that the microphone is in use.
- Optional: which app is in front, through `UsageStatsManager` (needs the *Usage access* permission).

The rules engine and config format (`profiles:` + `rules:`) would carry over unchanged.

### 2. Controlling the soundbar: blocked on decoding

The USB lighting commands are known, but the phone would talk to the soundbar over Bluetooth, and that protocol is
not decoded. Note also that on Windows the GS5's EQ, SuperWide and effects are not settings inside the soundbar at
all: Creative's PC driver applies them (see [PROTOCOL.md](PROTOCOL.md)). So it is an open question what the
soundbar itself can do for Bluetooth audio. Open questions, in order:

1. Can Creative's Android app change any GS5 setting over Bluetooth? Which ones: lighting only, or also sound
   settings that the soundbar applies on board? If none, a phone cannot either (except over a USB-C OTG cable,
   which defeats the point).
2. Does it use **BLE GATT** (characteristic writes) or classic Bluetooth (RFCOMM/SPP)? Android can do both from a
   background service; iOS could do neither in a useful way (see below).
3. Are the payloads the same `05 6a …` frames as over USB? Plausible, but unconfirmed.

With that answered, the app would be a small Kotlin app: `CompanionDeviceManager` to pair with the soundbar (this
also lets it run reliably in the background), a foreground service of type `connectedDevice`, the media listener
above, and `BluetoothGatt.writeCharacteristic()` for each frame, waiting for the reply like the USB driver does.

### How you can help: record an HCI snoop log

If you have a GS5 (or another Creative soundbar) and an Android phone with Creative's app:

1. Enable *Developer options* (tap *Build number* 7 times), then turn on **Enable Bluetooth HCI snoop log**.
2. Turn Bluetooth **off and on** so logging starts.
3. Open Creative's app, connect to the soundbar and do the same actions as in the
   [capture guide](CAPTURE_GUIDE.md): every sound setting the app offers for the soundbar (EQ presets top to
   bottom, SuperWide on/off, …) and a lighting colour change, waiting 5 seconds after each one. Write the order
   down in `notes.txt`, including which settings the app does *not* offer over Bluetooth.
4. Get the log. It is inside a bug report on most phones: `adb bugreport bugreport.zip`, then look for
   `FS/data/log/bt/btsnoop_hci.log` (some phones also save it under `/sdcard/` or `/sdcard/Android/data/`).
5. Turn the HCI snoop log **off** again.
6. Extract only the writes to the soundbar, for example with Wireshark's `tshark`:

   ```bash
   tshark -r btsnoop_hci.log -Y "btatt.opcode == 0x12 || btatt.opcode == 0x52 || btatt.opcode == 0x1b" \
     -T fields -e frame.time_relative -e bthci_acl.dst.bd_addr -e btatt.opcode -e btatt.handle -e btatt.value
   ```

   (`0x12`/`0x52` are writes from the phone, `0x1b` are notifications back from the soundbar.) If this prints
   nothing, the app probably uses classic Bluetooth: try the filter `btspp || btrfcomm` instead.
7. Open a [decoded command submission](https://github.com/esmobg/soundbar-autoprofile/issues/new?template=decoded_command.yml)
   with the output, `notes.txt`, your phone model and the Creative app version.

> **Privacy:** the raw `btsnoop_hci.log` and the bug report contain all Bluetooth traffic and a lot of system
> information from your phone (paired devices, possibly contacts synced to a car). Share the filtered output, not
> the raw files.

## iOS: not feasible

This is a platform limit, not a missing feature:

- **No way to see what other apps play.** iOS has no public API that tells an app what Spotify, Netflix, YouTube or
  Safari are playing. `MPNowPlayingInfoCenter` only describes the app's own playback, and
  `MPMusicPlayerController.systemMusicPlayer` only covers Apple's Music app. There is no equivalent of Android's
  notification listener.
- **No background work to react with.** iOS suspends apps in the background. A Bluetooth background mode exists,
  but it only wakes an app for events *from* the accessory, not because something started playing elsewhere.
- **Bluetooth limits.** Classic Bluetooth accessories (RFCOMM/SPP) are only reachable through Apple's MFi program,
  which the GS5 is not part of. BLE would be reachable, but only by an app built for it.
- **Shortcuts cannot talk to it.** Shortcuts has no action that sends Bluetooth data to an arbitrary device, and
  Creative's app does not offer Shortcuts actions for these settings as far as we know. The closest possible thing
  would be a dedicated iOS app that exposes "set profile" as an App Intent, triggered by a Shortcuts automation such
  as "when Netflix is opened". That is per-app, not per-content, depends on a BLE protocol nobody has decoded yet, and
  is not planned. Contributions welcome if the protocol turns out to be BLE.

### What iOS users can do instead

- Use Creative's own app on the phone to switch by hand, if it supports your soundbar.
- If the soundbar is also connected to a computer by USB-C, the computer can still change the **lighting** while
  the phone plays (`gs5 set music`, or the tray menu). Sound Modes on the computer do not affect the phone's
  Bluetooth audio, because Creative's processing runs on the PC.
- Set `default_profile` in the config to the profile (lighting) you want while the computer is idle.

---

## Накратко на български

- **Android е възможен по-нататък.** Какво се пуска се вижда с публични API (`NotificationListenerService` +
  `MediaSessionManager`), а разговорите с `AudioManager`. Липсва другата половина: Bluetooth протоколът на
  саундбара още не е разгадан и не е ясно какво от звука може да се сменя в самия саундбар (под Windows EQ и
  ефектите се прилагат от драйвера на компютъра). Помогни, като запишеш **Bluetooth HCI snoop log** от телефона, докато сменяш
  настройките в приложението на Creative (стъпките са по-горе; правиш същите действия като в
  [ръководството за запис](CAPTURE_GUIDE.md)). Споделяй само филтрирания резултат, не суровия лог.
- **iOS не е възможен.** iOS не позволява на приложение да вижда какво пускат други приложения, приспива
  приложенията във фонов режим и няма действие в Shortcuts, което да праща команди на саундбара.
- **Какво може на iPhone:** сменяй на ръка с приложението на Creative, ако поддържа саундбара ти. Ако саундбарът е
  свързан и с компютър по USB-C, компютърът може да сменя **осветлението**, докато телефонът свири (`gs5 set music`
  или менюто в трея). Звуковите режими на компютъра не влияят на звука от телефона по Bluetooth, защото
  обработката на Creative върви на компютъра.
