SwingScribe -- jazz audio in, swing-aware notation out
=======================================================

This folder is the whole program. Nothing needs to be installed.

Getting started
---------------
1. Keep this folder somewhere with a short path, such as C:\SwingScribe
   or directly under Documents. A very deep path can hit Windows' path
   length limit part-way through extraction.
2. Double-click setup.cmd once. It puts a SwingScribe icon on the desktop
   and in the Start Menu, and adds SwingScribe to Settings > Apps.
3. Double-click the SwingScribe icon. A console window opens minimized and
   the app opens in your browser at http://127.0.0.1:8420/.
4. To stop, click Quit at the top right of the page. Closing the browser
   tab does not stop it.

The first time Windows runs a script that came from the internet it may
show "Windows protected your PC". Click "More info", then "Run anyway".
This happens once per script.

The first run of each step (beats, separation, transcription) downloads
that step's model weights -- about half a gigabyte all told, once -- into
%LOCALAPPDATA%\SwingScribe\models. The progress bar says so while it
happens.

What it writes, and where
-------------------------
- %LOCALAPPDATA%\SwingScribe\models   downloaded model weights
- %LOCALAPPDATA%\SwingScribe\cache    separated stems and other derived data
                                      (safe to delete; the app's cache panel
                                      can do it per track)
- <track>.swingscribe.json            beside each audio file you open: your
                                      span, downbeat, edits and score link.
                                      Yours to keep; it is what makes a
                                      track open the way you left it.
Nothing goes on PATH or into the registry apart from the Settings > Apps
entry. A Python already on this computer is neither used nor touched.

Configuration
-------------
swingscribe.yaml in this folder is the configuration the launcher uses;
every setting is commented. gui.library_dir sets where the track picker
starts (the launcher defaults it to your Music folder).

Updating
--------
Extract the new version to a new folder, run its setup.cmd, delete the old
folder. The downloaded weights and the cache are shared, so nothing is
downloaded again.

Uninstalling
------------
Double-click uninstall.cmd, or use Settings > Apps > SwingScribe >
Uninstall. It removes the icons, the Apps entry, this folder, and -- only
if you say yes -- the data folder above. It never touches the
.swingscribe.json files beside your music.

If something goes wrong
-----------------------
- The console window that opens with the app is where an error shows.
  It stays open on an error; the last lines are the reason.
- "An Application Control policy has blocked this file" or a window that
  closes instantly on a new laptop: Windows' Smart App Control has refused
  a file. Every file in this folder was checked against it before release,
  but its verdicts change over time. Windows Security > App & browser
  control > Smart App Control settings lets an administrator turn it off;
  since the April 2026 Windows update it can be turned back on afterwards.
- Model weights will not download: check the network, then try again;
  a partial download is re-fetched.
- A download fails with "CERTIFICATE_VERIFY_FAILED" (most often on the
  first Separate): your network inspects encrypted traffic, as many
  workplaces and some antivirus products do, and signs it with its own
  certificate. Windows trusts that certificate; SwingScribe's downloader
  does not until you tell it to:
    1. Get the network's root certificate as a "Base-64 encoded" .cer
       file. Your IT department can supply it. Or find it yourself: open
       https://github.com in your browser, click the padlock, view the
       certificate, and the top of the chain is the root. If it is not a
       public authority (it names your company or your antivirus), export
       it as Base-64.
    2. Copy python\Lib\site-packages\certifi\cacert.pem from this folder
       to a folder of its own, for example C:\SwingScribe-certs\, so an
       update does not delete it. Open the copy in Notepad, paste the
       whole text of the .cer file at the end, and save.
    3. Start > "Edit environment variables for your account" > New, twice:
       SSL_CERT_FILE and REQUESTS_CA_BUNDLE, both set to that file, for
       example C:\SwingScribe-certs\cacert.pem.
    4. Quit SwingScribe and start it again from the icon.
- "The separation process crashed" and a mention of memory: separation
  needs a few GB of free memory. Close other programs and try again, or
  choose htdemucs in the separator menu, a much smaller model.

The user guide (the Help button in the app) covers every control.
Licences of the models and libraries: NOTICES.md beside this file.
