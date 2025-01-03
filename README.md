# 🏋️‍♂️ Fulcrum Fitness Tracker

A Home Assistant integration to track your training sessions at Fulcrum Fitness PDX.

## 🌟 Features

- Track total training sessions
- Monitor sessions with each trainer
- View upcoming scheduled sessions
- Track personal records (PRs)
- Cost analysis per session
- Calendar integration
- Training progress visualization

## 📊 Available Sensors

- Total training sessions
- Sessions per trainer
- Monthly session count
- Last/Next scheduled session
- Recent PRs
- Cost per session metrics
- Training streaks

## 🛠️ Installation

### HACS Installation
1. Open HACS in Home Assistant
2. Click the "+" button
3. Search for "Fulcrum Fitness Tracker"
4. Click "Install"
5. Restart Home Assistant

### Manual Installation
1. Download the latest release
2. Copy the `fulcrum_tracker` folder to `custom_components` in your Home Assistant config directory
3. Restart Home Assistant

## ⚙️ Configuration

1. Go to Settings → Devices & Services
2. Click "+ Add Integration"
3. Search for "Fulcrum Fitness Tracker"
4. Follow the configuration steps:
   - Enter your ZenPlanner credentials
   - Configure Google Calendar integration
   - Set monthly cost settings (optional)

## 📱 Lovelace Card Examples

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Fulcrum Training Stats
    entities:
      - sensor.total_fulcrum_sessions
      - sensor.monthly_sessions
      - sensor.last_session
      - sensor.next_session
```

## 🔧 Requirements

- Active Fulcrum Fitness PDX membership
- ZenPlanner account
- Google Calendar with training sessions
- Home Assistant 2024.1.0 or newer
- HACS 2.0.0 or newer

## 🤝 Contributing

Contributions are welcome! Please read the [contributing guidelines](CONTRIBUTING.md) before submitting pull requests.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🐛 Known Issues

- Rate limiting may affect data refresh times
- Calendar sync may be delayed by up to 15 minutes
- PR tracking requires manual session tagging

## 🙏 Acknowledgments

- Fulcrum Fitness PDX Community
- Home Assistant Community
- HACS Team

## ❓ Support

- Report issues on [GitHub](https://github.com/stoffee/fulcrum_tracker/issues)
- Join discussions in [Home Assistant Community](https://community.home-assistant.io)

---
💪 Made with love for the Fulcrum Fitness community