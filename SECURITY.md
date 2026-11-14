# Security policy

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue:

1. Go to the repository's **Security** tab and choose **Report a vulnerability**
   (<https://github.com/esmobg/soundbar-autoprofile/security/advisories/new>).
2. Describe the problem, the affected version (`gs5 --version`) and operating system, and how to reproduce it.

We aim to reply within a week. Once a fix is released, the advisory is published and you are credited
unless you prefer otherwise.

## Supported versions

Only the latest release receives security fixes.

## Scope

In scope, for example:

- Code execution or privilege escalation through the config file, the autostart entry, the udev rule or the
  capture decoder (`gs5 decode-capture` parses files that may come from others).
- The tool sending commands to a device other than the configured soundbar, or commands that can damage it.
- The Windows UI Automation used for Sound Modes acting on any window other than Creative App's.
- Personal data (window and track titles, app names) leaking anywhere other than the local log file.
- Problems in how the package is built or published.

Out of scope:

- Vulnerabilities in the soundbar's firmware, in Creative App or in other Creative software: report those to
  Creative Technology Ltd.
- Issues in dependencies (hidapi, PyYAML, psutil, …) that do not affect this project: report them upstream.
- Someone with access to your user account editing your config file: that person can already run any program as
  you.

The tool has no network code and no telemetry. If you find that it opens a network connection, that is a bug worth
reporting.
