from typing import List
import paho.mqtt.client as mqtt
import json
import logging

class HassActionConfig:
    config_topic: str
    config_entity: dict
    
    def __init__(self, config_topic: str, config_entity: dict) -> None:
        self.config_topic = config_topic
        self.config_entity = config_entity

class HassConfig:
    mqttClient: mqtt.Client
    name: str
    sensor_name: str
    subject: str
    
    def __init__(self, mqttClient: mqtt.Client) -> None:
        self.mqttClient = mqttClient
    
    def publish_sensor_config(self, name: str, sensor_name: str, subject: str) -> None:
        data = json.dumps(self.__vm_status_to_homeassistant_config(name=name, sensor_name=sensor_name, subject=subject))
        self.mqttClient.publish(f"homeassistant/sensor/virsh/{name.lower()}_{subject.lower()}/config", data, retain=True)
    
    def publish_binary_sensor_config(self, name: str, sensor_name: str, subject: str) -> None:
        config = self.__vm_status_to_homeassistant_config(name=name, sensor_name=sensor_name, subject=subject)
        
        # Legg til payload_on og payload_off
        config["payload_on"] = "true"  # Payload for "on" status
        config["payload_off"] = "false"  # Payload for "off" status
        config["device_class"] = "power"
        
        # Publiser konfigurasjonen til Home Assistant
        data = json.dumps(config)
        self.mqttClient.publish(f"homeassistant/binary_sensor/virsh/{name.lower()}_{subject.lower()}/config", data, retain=True)
        self.__publish_button_config(name=name)
    
    def __publish_button_config(self, name: str) -> None:
        running_availability_topic = f"virsh/vm/{name}/running"
        status_availability_topic = f"virsh/vm/{name}/status"
        
        button_entity: List[HassActionConfig] = [
            self.__create_vm_start_button(vm_name=name, running_topic=running_availability_topic, status_topic=status_availability_topic),
            self.__create_vm_pause_button(vm_name=name, running_topic=running_availability_topic, status_topic=status_availability_topic),
            self.__create_vm_stop_button(vm_name=name, running_topic=running_availability_topic, status_topic=status_availability_topic),
            self.__create_vm_force_stop_buttom(vm_name=name, running_topic=running_availability_topic, status_topic=status_availability_topic)
        ]            
        
        for cf in button_entity:
            jd = json.dumps(cf.config_entity)
            logging.debug(f"Configuring button for topic {cf.config_topic}\n{jd}")
            self.mqttClient.publish(cf.config_topic, jd, retain=True)
        
    def __create_vm_start_button(self, vm_name: str, running_topic: str, status_topic: str) -> HassActionConfig:
        icon = "mdi:play"
        title = "Play"
        action = "play"
        
        config_payload = {
            "name": title,
            "icon": icon,  # Add icon to the configuration
            "unique_id": f"vm_{vm_name.lower()}_button_{action}",
            "payload_press": action,
            "availability": [
                {
                    "payload_available": "True",
                    "payload_not_available": "False",
                    "value_template": "{{ value not in ['shutdown', 'running'] }}",
                    "topic": status_topic
                }
            ],
            "command_topic": f"homeassistant/button/virsh/{vm_name}/{action}/set",
            "device": self.__vm_to_homeassistant_device_config(vm_name)
        }
        
        return HassActionConfig(config_topic=f"homeassistant/button/virsh/{vm_name}_{action}/config", config_entity=config_payload)
    
    def __create_vm_pause_button(self, vm_name: str, running_topic: str, status_topic: str) -> HassActionConfig:
        icon = "mdi:pause"
        title = "Pause"
        action = "pause"
        config_payload = {
            "name": title,
            "icon": icon,  # Add icon to the configuration
            "unique_id": f"vm_{vm_name.lower()}_button_{action}",
            "payload_press": action,
            "availability": [
                {
                    "payload_available": "true",
                    "payload_not_available": "false",
                    "topic": running_topic
                },
                {
                    "payload_available": "false",
                    "payload_not_available": "true",
                    "value_template": "{{ value not in ['suspend'] }}",
                    "topic": status_topic
                }
            ],
            "command_topic": f"homeassistant/button/virsh/{vm_name}/{action}/set",
            "device": self.__vm_to_homeassistant_device_config(vm_name)
        }
        
        return HassActionConfig(config_topic=f"homeassistant/button/virsh/{vm_name}_{action}/config", config_entity=config_payload)
    
    def __create_vm_stop_button(self, vm_name: str, running_topic: str, status_topic: str) -> HassActionConfig:
        icon = "mdi:stop"
        title = "Shutdown"
        action = "stop"
        config_payload = {
            "name": title,
            "icon": icon,  # Add icon to the configuration
            "unique_id": f"vm_{vm_name.lower()}_button_{action}",
            "payload_press": action,
            "availability": [
                {
                    "payload_available": "true",
                    "payload_not_available": "false",
                    "topic": running_topic
                },
                {
                    "payload_available": "false",
                    "payload_not_available": "true",
                    "value_template": "{{ value not in ['shutdown'] }}",
                    "topic": status_topic
                }
            ],
            "command_topic": f"homeassistant/button/virsh/{vm_name}/{action}/set",
            "device": self.__vm_to_homeassistant_device_config(vm_name)
        }
        
        return HassActionConfig(config_topic=f"homeassistant/button/virsh/{vm_name}_{action}/config", config_entity=config_payload)
    
    def __create_vm_force_stop_buttom(self, vm_name: str, running_topic: str, status_topic: str) -> HassActionConfig:
        icon = "mdi:power"
        title = "Force Off"
        action = "destroy"
        config_payload = {
            "name": title,
            "icon": icon,  # Add icon to the configuration
            "unique_id": f"vm_{vm_name.lower()}_button_{action}",
            "payload_press": action,
            "availability": [
                {
                    "payload_available": "true",
                    "payload_not_available": "false",
                    "topic": running_topic
                }
            ],
            "command_topic": f"homeassistant/button/virsh/{vm_name}/{action}/set",
            "device": self.__vm_to_homeassistant_device_config(vm_name)
        }
        
        return HassActionConfig(config_topic=f"homeassistant/button/virsh/{vm_name}_{action}/config", config_entity=config_payload)
        
    
    def __vm_status_to_homeassistant_config(self, name: str, sensor_name: str, subject: str) -> dict:
        return {
            "name": f"{sensor_name}",
            "state_topic": f"virsh/vm/{name}/{subject}",
            "unique_id": f"vm_{name.lower()}_status",
            "device": self.__vm_to_homeassistant_device_config(name)
        }
    
    def __vm_to_homeassistant_device_config(self, name: str) -> dict:
        uName = name.replace("_", " ").capitalize()
        return {
                "identifiers": [ f"{name}" ],
                "name": f"VM {uName}",
                "model": "QEMU Virtual Machine",
                "manufacturer": "Libvirt"
            }    