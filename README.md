# Home Climate System

Home Assistant custom component for advanced climate control with enhanced PID logic.

## Features

- Advanced PID temperature control algorithm 
- Support for multiple preset modes (none, away, boost, comfort)
- Boiler state management and modulation control
- Integration with Home Assistant's climate platform
- Configurable PID parameters for different heating scenarios

## Installation

1. Copy the `home_climate_system` folder to your Home Assistant configuration directory under `custom_components/`
2. Restart Home Assistant
3. Add the integration through the UI or configure manually in `configuration.yaml`

## Configuration

```yaml
climate:
  - platform: home_climate_system
    name: "Home Climate System"
```

### PID Parameters (Advanced)

The component includes configurable PID parameters that can be adjusted for different heating systems:

- **Proportional Gain (Kp)**: Controls immediate response to temperature error  
- **Integral Gain (Ki)**: Eliminates steady-state error over time
- **Derivative Gain (Kd)**: Provides stability and reduces overshoot

### Preset Modes

- `none`: Normal operation with standard control logic
- `away`: Reduces target temperature by 3°C for energy savings  
- `boost`: Increases target temperature by 2°C for faster heating
- `comfort`: Maintains optimal comfort level (default behavior)

## Usage

The component works as a standard Home Assistant climate entity and supports all common operations:
- Setting target temperatures 
- Switching between HVAC modes (heat/off)
- Managing preset modes
- Monitoring current temperature readings