# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- Renamed the project to **Bodycam Overlay & Devkit** (was BDT Overlay Fork).
  The GitHub repo, packaged exe (`BodycamOverlayDevkit.exe`), and the
  `%LOCALAPPDATA%\BodycamOverlayDevkit\` config folder all moved to match.

## [1.0.0] — 2026-09-12

### Changed
- ClaudeBridge (the in-game mod) now detects when a newer version is bundled
  with the overlay and redeploys it automatically. **After updating, fully
  restart Bodycam once** so the game picks up the new mod.
- Private matches now get a random session password each time the overlay
  starts, instead of a fixed one shared by every install — the Host tab shows
  it in a persistent label after loading a private match.
- The overlay no longer piles up connection checks at startup: it used to
  take up to ~65 seconds to report "not responding" with the game closed;
  it's now near-instant.
- A hand-edited `families.json`/`maps.json`/`gamemodes.json` that's corrupt is
  now reported with a real error dialog naming the file, instead of the app
  silently failing to start.
- The window now sizes itself to 70% of your screen (DPI-aware) instead of a
  fixed 1920×1080, and every dialog is now properly modal (it used to be
  possible to click through to the main window behind one).

### Fixed
- The Auto-Clear cooldown timer could double up (running two overlapping
  timers, each re-clearing the cooldown) if toggled off and back on quickly.
- Status/connection colors are visually distinct again (a leftover from an
  earlier palette change made "connected" and "error" render identically).
- Keyboard focus is now visible on every button/checkbox/radio button, and
  `Ctrl+Tab` switches between tabs.
- Four "unconfirmed" maps (Assylum, Village, Pit, Logistics) that don't
  actually exist in the game's files were removed from the map picker.

### Added
- A visible version number (Bodycam Overlay v1.0.0), shown in the window
  title and the About tab.

## Earlier

Everything before this changelog existed is summarized in the commit history.
