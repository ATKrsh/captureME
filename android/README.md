# captureME for Android & Mobile Devices

`captureME` for Android is a high-performance, mobile-optimized screen recorder and screenshot capture application featuring a real-time audio-reactive breathing orb interface.

---

## 🌟 Key Features
- **Audio-Reactive Breathing Orb**: HTML5 Canvas engine with Web Audio API real-time spectral analyzer (reacting live to volume amplitude & sound frequencies).
- **Screen & Audio Recording**: Instant screen recording via MediaRecorder API with WebM/MP4 output saved directly to Android downloads.
- **Screenshot Generator**: One-touch screen frame grab with visual flash feedback.
- **Mobile Touch Gestures**: Drag the floating orb around the screen, tap the center dot to toggle recording, tap the orb ring to take screenshots.
- **Glassmorphism Settings Drawer**: Dynamic sliders for App Opacity, Glow Opacity, Glow Radius, Orb Size, Breathing Animation, and Audio Spectrum toggles.
- **Android PWA Support**: Complete Web App Manifest and Service Worker allowing one-touch **"Add to Home Screen"** installation on Android.

---

## 📱 How to Run on Android

### Option A: Install as Android PWA (Recommended)
1. Host or open `index.html` in Chrome or Firefox on your Android device (or via local Wi-Fi / local server).
2. Open the Chrome menu (⋮) and tap **"Add to Home screen"** or **"Install app"**.
3. `captureME` will install as a standalone native-feeling Android application on your home screen!

### Option B: Build as Native Android APK (.apk)
To bundle into a native Android APK:
1. Initialize Capacitor in this folder:
   ```bash
   npx @capacitor/cli create
   ```
2. Add the Android platform:
   ```bash
   npx cap add android
   ```
3. Open in Android Studio and build APK:
   ```bash
   npx cap open android
   ```

---

## 🖥️ Desktop Cross-Platform (macOS & Windows)
For macOS and Windows, run the desktop PyQt5 application located in the parent directory:
```bash
python main.py
```
To bundle for macOS:
```bash
python build_mac.py
```
