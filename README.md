# Smart Meeting

Live transcription and automatic minutes for your meetings, **100% local**: nothing you say or hear leaves your
computer.

During a call (Teams, Meet, Zoom…), Smart Meeting listens to your microphone and to your headset, writes down who says
what, answers your questions about the meeting, and writes the minutes at the end.

![Home page](docs/images/start.png)

## Install

You only need **git**. The first launch installs everything else (no admin rights).

| System | Install once | Launch |
|---|---|---|
| **Ubuntu** 22.10+ | `sudo apt install git` | `./smart-meeting` |
| **macOS** 13+ | `xcode-select --install` | `./smart-meeting` in the Terminal |
| **Windows** 10/11 | `winget install Git.Git` | `.\smart-meeting` in PowerShell, or double-click `smart-meeting.cmd` |

```bash
git clone https://github.com/graffkevin/smart-meeting.git
cd smart-meeting
./smart-meeting          # Windows: .\smart-meeting
```

The first launch downloads about 8 GB (AI and transcription models): 10 to 30 minutes. You can already record
meanwhile. The next launches take a few seconds.

To update: `git pull`, then launch again.

## Put it in your dock or taskbar

Run once, in the project folder:

```bash
./smart-meeting --install          # Windows: .\smart-meeting --install
```

| System | Then |
|---|---|
| **Ubuntu** | Super key, type "Smart Meeting", right-click, **Pin to Dash** |
| **macOS** | in the Finder, open your **Applications** folder (Go > Home > Applications) and drag **Smart Meeting** to the Dock |
| **Windows** | Start menu, right-click **Smart Meeting**, **Pin to taskbar** |

## Use it

### 1. Start a meeting

Click the Smart Meeting icon: the app opens in your browser. Give the meeting a name if you like, click **Start
recording**, then start your call. Smart Meeting follows the microphone and the headset your call uses.

### 2. Follow, and ask

![A meeting](docs/images/meeting.png)

- The **transcript** appears live on the right: your sentences on one side, the others on the other.
- Each person has a colored label ("Speaker 1", "Speaker 2"…). **Double-click a label** to name that person in the
  whole meeting. Giving the name of another speaker merges both.
- **Ask the meeting** at any time: **Summary**, **My actions**, **Decisions**, or your own question. The answer
  gives the time of the passages it relies on.

### 3. Stop and get the minutes

Click **Stop recording**. The local AI writes the minutes: summary, actions with who and when, decisions, open
questions, watch points. **Copy the minutes** gives them as text, ready to paste in an email or a wiki.

![Minutes](docs/images/minutes.png)

### 4. Find your meetings

The **history** on the right lists your meetings by date or by tag. The search finds a word in everything that was
said.

### Also

- **Import a recording** (call replay, webinar, voice note): "Choose a file" on the home page.
- **Settings** (⚙ at the top): your name, a vocabulary of names and acronyms to recognize, the microphone and
  headset, keep the audio or not, and **Meeting room** when several people speak into your microphone.
- **FR | EN** at the top switches the interface, the AI answers and the minutes.
- **Closing the tab** stops the app once nothing is running. A recording goes on if you close the tab by mistake.

<img src="docs/images/settings.png" alt="Settings" width="400">

## Good to know

- **Nothing said is lost.** The sound is kept on your computer during the meeting, just in case. If the
  transcription stops, it restarts by itself and catches up on what was missing. The sound is then deleted, unless
  you choose to keep it.
- **Long meetings** (2 or 3 hours) are fine: the AI reads the whole meeting.
- **The AI can be slow** without a large graphics card: about 2 minutes for a first question on a 30-minute meeting,
  less than one for the next ones, a few minutes for the minutes. The transcription goes on meanwhile.
- **macOS**, first meeting: a message asks to let Smart Meeting hear the computer. Click **Open the settings**, turn
  on **Terminal** (or **Smart Meeting** if you start it from the Dock), then **Quit & Reopen**. Done once for all.
- Tested on Linux. Windows and macOS are **not tested yet**.

## Privacy

Everything runs on your computer: the transcription, the AI, the storage. No audio, no transcript, no question ever
goes on the Internet. The downloads only fetch the software and the models.

## More

How it works, advanced settings, development: [docs/TECHNICAL.md](docs/TECHNICAL.md). Design choices (in French):
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

[MIT license](LICENSE). Speakers are told apart with the [WeSpeaker](https://github.com/wenet-e2e/wespeaker)
ResNet34-LM model (VoxCeleb), [CC BY 4.0](https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM).
