<!-- Source: https://docs.entire.io/installation | Scraped: 2026-10-10 -->

> ## Documentation Index
>
> Fetch the complete documentation index at: [/llms.txt](https://docs.entire.io/llms.txt)
>
> Use this file to discover all available pages before exploring further.

[Skip to main content](https://docs.entire.io/installation#content-area)

[Entire home page![light logo](https://mintcdn.com/entire/dU84oUx3gFbNHZ8_/logo/light.svg?fit=max&auto=format&n=dU84oUx3gFbNHZ8_&q=85&s=6ce790665b11c249fbf9d14a33f846c4)![dark logo](https://mintcdn.com/entire/dU84oUx3gFbNHZ8_/logo/dark.svg?fit=max&auto=format&n=dU84oUx3gFbNHZ8_&q=85&s=4499c6eb37e0fdff05bed2f478dfe874)](https://entire.io/)

Search...

Ctrl KAsk AssistantCTRLI

- [Status](https://status.entire.io/)
- [Quickstart](https://docs.entire.io/quickstart)
- [Quickstart](https://docs.entire.io/quickstart)

Search...

Navigation

Getting Started

Installation

[Documentation](https://docs.entire.io/) [Agents](https://docs.entire.io/agents/overview) [CLI Reference](https://docs.entire.io/cli-reference/activity) [Learn](https://docs.entire.io/learn/overview)

- [GitHub](https://github.com/entireio)
- [Discord](https://discord.gg/jZJs3Tue4S)
- [Blog](https://entire.io/blog)

### Getting Started

- [Introduction](https://docs.entire.io/)
- [Quickstart](https://docs.entire.io/quickstart)
- [Installation](https://docs.entire.io/installation)
- [Entire CLI and entire.io](https://docs.entire.io/platforms/cli-and-entire-io)

### Guides

- Code Hosting

- Session Storage

- Agentic Search

- Continuous Memory

- Any Agent

- Dispatches

- Configuration


### Migration

- [Migrate from GitHub](https://docs.entire.io/migration/migrate-from-github)

### Security

- [Security & Privacy](https://docs.entire.io/security)

### Resources

- [FAQ](https://docs.entire.io/faq)
- [Glossary](https://docs.entire.io/glossary)
- [Delete Your Account](https://docs.entire.io/delete-account)

## On this page

- [System Requirements](https://docs.entire.io/installation#system-requirements)
- [Release Channels](https://docs.entire.io/installation#release-channels)
- [Install and Update Entire](https://docs.entire.io/installation#install-and-update-entire)
- [Verify the Installation](https://docs.entire.io/installation#verify-the-installation)
- [Installation and Data Locations](https://docs.entire.io/installation#installation-and-data-locations)
- [Control Update Prompts](https://docs.entire.io/installation#control-update-prompts)
- [Shell Completion](https://docs.entire.io/installation#shell-completion)
- [Uninstall Entire](https://docs.entire.io/installation#uninstall-entire)
- [Review Recent Changes](https://docs.entire.io/installation#review-recent-changes)

Getting Started

# Installation

Copy pageCopy page

Install, update, verify, and uninstall the Entire CLI.

Copy pageCopy page

## [​](https://docs.entire.io/installation\#system-requirements)  System Requirements

- macOS, Linux, or Windows
- Git 2.25 or later
- Bash, Zsh, Fish, or PowerShell
- Windows PowerShell 5.1 or later, for the Windows PowerShell installer

Building from source requires Go 1.26.6 or later.

## [​](https://docs.entire.io/installation\#release-channels)  Release Channels

Entire ships two release channels:

- `stable`: the default channel for Homebrew, Scoop, `install.sh`, and `install.ps1`
- `nightly`: prerelease builds available through Homebrew, `install.sh`, and `install.ps1`

Scoop supports the stable channel only. For a nightly install on Windows, use `install.ps1`.

## [​](https://docs.entire.io/installation\#install-and-update-entire)  Install and Update Entire

Choose one installation method. Use the update command in the same tab when you want a newer release.

- macOS with Homebrew

- Linux Install Script

- Linux Direct Download

- Windows with PowerShell

- Windows with Scoop

- Build from Source


Install the stable channel:

```
brew install --cask entireio/tap/entire
```

Or install the nightly channel:

```
brew install --cask entireio/tap/entire@nightly
```

The fully qualified cask name adds the `entireio/tap` tap for you, so no separate `brew tap` step is needed.Update the channel you installed:

```
brew upgrade --cask entireio/tap/entire
```

```
brew upgrade --cask entireio/tap/entire@nightly
```

Install the stable channel:

```
curl -fsSL https://entire.io/install.sh | bash
```

Or install the nightly channel:

```
curl -fsSL https://entire.io/install.sh | bash -s -- --channel nightly
```

The script installs `entire` and `git-remote-entire` in `~/.local/bin`. If that directory is missing from your `PATH`, the script prints the command that adds it to your shell configuration.Run the command for your channel again to update Entire.

Download the stable AMD64 archive and install both executables:

```
download_dir="$(mktemp -d)"
mkdir -p "$HOME/.local/bin"
curl -fsSL https://github.com/entireio/cli/releases/latest/download/entire_linux_amd64.tar.gz \
  -o "$download_dir/entire_linux_amd64.tar.gz"
tar -xzf "$download_dir/entire_linux_amd64.tar.gz" -C "$download_dir"
install -m 0755 "$download_dir/entire" "$download_dir/git-remote-entire" "$HOME/.local/bin/"
rm -rf "$download_dir"
```

For ARM64, replace `amd64` with `arm64` in the archive name:

```
download_dir="$(mktemp -d)"
mkdir -p "$HOME/.local/bin"
curl -fsSL https://github.com/entireio/cli/releases/latest/download/entire_linux_arm64.tar.gz \
  -o "$download_dir/entire_linux_arm64.tar.gz"
tar -xzf "$download_dir/entire_linux_arm64.tar.gz" -C "$download_dir"
install -m 0755 "$download_dir/entire" "$download_dir/git-remote-entire" "$HOME/.local/bin/"
rm -rf "$download_dir"
```

Run the block for your architecture again to update Entire.

Install the stable channel from Windows PowerShell 5.1 or later:

```
irm https://entire.io/install.ps1 | iex
```

Or install the nightly channel:

```
iex "& {$(irm https://entire.io/install.ps1)} -Channel nightly"
```

For the stable channel, the script uses Scoop when Scoop is on your `PATH`, and it adds the Entire bucket first. Without Scoop, and for every nightly install, the script verifies the release checksum, installs `entire.exe` and `git-remote-entire.exe` in `%USERPROFILE%\.local\bin`, and adds that directory to your user `PATH`. Restart your terminal after the script changes your `PATH`.The script accepts these options. Pass them with the script block form shown for the nightly channel, because `irm | iex` cannot forward arguments:

| Option | Effect |
| --- | --- |
| `-Channel` | Release channel to install, `stable` or `nightly`. Defaults to `stable`. |
| `-InstallDir` | Destination for a checksum verified install. Defaults to `$HOME\.local\bin`. Passing it selects the release archive even when Scoop is available. |
| `-NoPathUpdate` | Leave your user `PATH` unchanged. Applies to release archive installs, because Scoop manages its own `PATH` entry. |
| `-Help` | Print the usage message. |

In Git Bash, MSYS, or Cygwin, `install.sh` stops and points you to this installer.

Run the command for your channel again to update Entire.

These commands drive Scoop directly. The PowerShell installer already uses Scoop for stable installs when Scoop is available.Add the Entire bucket once, then install the stable channel:

```
scoop bucket add entire https://github.com/entireio/scoop-bucket.git
scoop install entire/entire
```

Update Scoop and Entire:

```
scoop update
scoop update entire
```

Use `entire/entire` for new installations. Scoop previously used `entire/cli`.

Install both executables:

```
go install github.com/entireio/cli/cmd/entire@latest
go install github.com/entireio/cli/cmd/git-remote-entire@latest
```

Go writes them to `$(go env GOPATH)/bin`. Add that directory to your `PATH` if your shell cannot find `entire`.Run both commands again to update the source installation.

## [​](https://docs.entire.io/installation\#verify-the-installation)  Verify the Installation

Run:

```
entire version
```

Entire CLI 0.10.5 prints three lines. The Go version and platform reflect the release and system you installed:

```
Entire CLI 0.10.5
Go version: go1.26.6
OS/Arch: darwin/arm64
```

Release archives also include `git-remote-entire`. Git invokes this helper when a remote uses an `entire://` URL. Verify that your shell can find both executables:

- macOS or Linux

- Windows


```
command -v entire
command -v git-remote-entire
```

```
Get-Command entire
Get-Command git-remote-entire
```

## [​](https://docs.entire.io/installation\#installation-and-data-locations)  Installation and Data Locations

The executable location depends on the installation method:

| Method | Location |
| --- | --- |
| Homebrew | The Homebrew prefix returned by `brew --prefix` |
| Linux install script or direct download | `~/.local/bin` |
| Windows PowerShell script without Scoop | `%USERPROFILE%\.local\bin`, or the `-InstallDir` you passed |
| Scoop | The directory returned by `scoop prefix entire` |
| Go | `$(go env GOPATH)/bin` |

Entire stores repository settings in `.entire/settings.json` and personal repository overrides in `.entire/settings.local.json`. See [Local, Project, and Global Settings](https://docs.entire.io/guides/configuration/settings-layers) for those files.The CLI also uses these directories for each user:

| Data | Default | Override |
| --- | --- | --- |
| Login contexts, update state, and file based credentials | `~/.config/entire` | `ENTIRE_CONFIG_DIR` |
| Discovery caches | `~/.cache/entire` | `XDG_CACHE_HOME`, with `/entire` appended |
| Managed CLI plugins on macOS and Linux | `~/.local/share/entire/plugins` | `ENTIRE_PLUGIN_DIR`, or `XDG_DATA_HOME` with `/entire/plugins` appended |

`XDG_CONFIG_HOME` does not change the Entire config directory. Set `ENTIRE_CONFIG_DIR` when you need a different location.

## [​](https://docs.entire.io/installation\#control-update-prompts)  Control Update Prompts

Set this variable in scripts, CI, or other environments where the CLI should not prompt for an update:

```
ENTIRE_NO_AUTO_UPDATE=1
```

## [​](https://docs.entire.io/installation\#shell-completion)  Shell Completion

Entire generates shell completion scripts for Bash, Zsh, Fish, and PowerShell with [`entire completion`](https://docs.entire.io/cli-reference/completion). The steps below cover Bash and Zsh.

- Bash

- Zsh


Add this command to `~/.bashrc`:

```
source <(entire completion bash)
```

Add this command to `~/.zshrc`:

```
source <(entire completion zsh)
```

## [​](https://docs.entire.io/installation\#uninstall-entire)  Uninstall Entire

Use the command that matches your installation method.

- Homebrew

- Linux Install Script or Direct Download

- Windows PowerShell Script

- Scoop

- Go


Stable:

```
brew uninstall --cask entireio/tap/entire
```

Nightly:

```
brew uninstall --cask entireio/tap/entire@nightly
```

```
rm -f "$HOME/.local/bin/entire" "$HOME/.local/bin/git-remote-entire"
```

Remove both executables from the directory you installed them in:

```
Remove-Item "$HOME\.local\bin\entire.exe", "$HOME\.local\bin\git-remote-entire.exe"
```

The user `PATH` entry for that directory remains. Remove it if you no longer need the directory. If the script used Scoop, follow the Scoop tab instead.

```
scoop uninstall entire
```

```
rm -f "$(go env GOPATH)/bin/entire" "$(go env GOPATH)/bin/git-remote-entire"
```

Uninstalling the executables does not remove repository settings, checkpoints, or user data. Inspect the paths under [Installation and Data Locations](https://docs.entire.io/installation#installation-and-data-locations) before removing data you no longer need.

## [​](https://docs.entire.io/installation\#review-recent-changes)  Review Recent Changes

Read the [Entire CLI changelog](https://github.com/entireio/cli/blob/main/CHANGELOG.md) for changes in each release.Continue to the [Quickstart](https://docs.entire.io/quickstart) to capture your first checkpoint.

Was this page helpful?

YesNo

[Quickstart\\
\\
Previous](https://docs.entire.io/quickstart) [Entire CLI and entire.io\\
\\
Next](https://docs.entire.io/platforms/cli-and-entire-io)

[x](https://x.com/entirehq) [github](https://github.com/entireio/cli) [discord](https://discord.gg/jZJs3Tue4S) [linkedin](https://www.linkedin.com/company/entireio) [website](https://entire.io/blog)

Assistant

Responses are generated using AI and may contain mistakes.