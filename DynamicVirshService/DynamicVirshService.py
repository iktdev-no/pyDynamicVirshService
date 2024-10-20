import logging, json, asyncio
from enum import Enum
from typing import List, Optional, Set
import threading
from threading import Thread
from .version import __version__

from .hassConfig import HassConfig
import libvirt
from libvirt import virConnect, virDomain
from .virshClient import VirshClient, VirshVM, VMStates
from .mqttClient import MqttClient

logging.basicConfig(level=logging.INFO)

class DynamicVirshService:
    qemu_address: str
    qemu_excluded_vms: List[str]
    qemu_allow_simultaneous_vms: bool = False
    
    mqttClient: MqttClient | None
    virshClient: VirshClient | None

    __vms_pushed: List[str] = []

    def __init__(self, configFile: str) -> None:
        self.virshClient = None
        logging.info(f"Version: {__version__}")
        config: dict = json.load(open(configFile))
        mqttConfig: dict = config["mqtt"]
        mqtt_brooker = mqttConfig["host"]
        mqtt_brooker_port = mqttConfig.get("port", 1883)
        mqtt_username = mqttConfig.get("username", None)
        mqtt_password = mqttConfig.get("password", None)
        
        self.mqttClient = MqttClient(brooker=mqtt_brooker, port=mqtt_brooker_port, username=mqtt_username, password=mqtt_password)
        
        qemuConfig: dict = config["qemu"]
        self.qemu_address = qemuConfig.get("address", "qemu:///system")
        self.qemu_excluded_vms = qemuConfig.get("excluded_vms", [])
        self.qemu_allow_simultaneous_vms = qemuConfig.get("allow_simultaneous_vms", False)
        
        logging.info(f"VMs in exclusion list are: {",".join(self.qemu_excluded_vms)}")
        logging.info(f"QEMU is set to {"Disallow" if self.qemu_allow_simultaneous_vms == False else "Allow"} simultaneous VMs")
        
        self.__connect_to_virsh()
        
    def __connect_to_virsh(self) -> None:
        if self.virshClient is None:
            logging.info("Opening a connection to Libvirt/QEMU")
            self.virshClient = VirshClient(self.qemu_address, self.__virsh_state_update)    
        else:
            try:
                self.virshClient.client.close()
            except Exception as e:
                logging.info("Libvirt/QEMU connection was already closed or failed")
            logging.info("Re-opening a connection to Libvirt/QEMU")
            self.virshClient = VirshClient(self.qemu_address, self.qemu_allow_simultaneous_vms, self.__virsh_state_update)


    def is_excluded(self, name: str) -> bool:
        for excludedName in self.qemu_excluded_vms:
            if (excludedName.strip().lower() == name.strip().lower()):
                logging.info(f"VM {name} is excluded")
                return True
            else:
                logging.debug(f"VM: {name} does not match excluded: {excludedName}")
        return False

    def start(self) -> None:
        self.mqttClient.set_event_callback(self.__on_mqtt_action_received)
        self.mqttClient.start()   
        
        for vm in self.virshClient.get_vms():
            self.__virsh_state_update(vm)
            self.__vms_pushed.append(vm.name)

        self.virshClient.start()

    def stop(self) -> None:
        self.virshClient.stop()
        self.mqttClient.stop()

    def __virsh_state_update(self, vmInfo: VirshVM):
        """
        Push data to mqtt
        """
        
        any_vm_running = any(vm.state != "shut off" for vm in self.virshClient.get_vms())
        disable_actions = False if self.qemu_allow_simultaneous_vms else any_vm_running
        self.mqttClient.publish(f"virsh/vm/actions_disabled", disable_actions, retain=True) 

        if (self.is_excluded(vmInfo.name) == False):
            if (vmInfo.name not in self.__vms_pushed):
                hassConfig = HassConfig(mqttClient=self.mqttClient)
                hassConfig.publish_sensor_config(name=vmInfo.name, sensor_name=f"{vmInfo.name} Status", subject="status")
                hassConfig.publish_binary_sensor_config(name=vmInfo.name, sensor_name=f"{vmInfo.name} Running", subject="running")
                self.__vms_pushed.append(vmInfo.name)
                
            self.mqttClient.publish_vm_subject(name = vmInfo.name, subject = "status", value = vmInfo.state)
            publish_value = "true" if vmInfo.state != "shut off" else "false"
            self.mqttClient.publish_vm_subject(name=vmInfo.name, subject="running", value=publish_value)
            
    def __on_mqtt_action_received(self, vm_name, vm_action) -> None:
        virshCommand = VirshCommand(self.virshClient, self.mqttClient, vm_name, vm_action)
        try:
            virshCommand.execute()
        except Exception as e:
            logging.error("An error occured while trying to executa a virsh command!")
            logging.exception(e)
            self.__connect_to_virsh()
            self.mqttClient.publish_vm_subject(name=vm_name, subject="status", value="failed")




class VirshCommand():
    virshClient: VirshClient
    mqttClient: MqttClient
    name: str
    command: str
    def __init__(self, client: VirshClient, mqtt: MqttClient, name: str, command: str) -> None:
        self.name = name
        self.command = command
        self.virshClient = client
        self.mqttClient = mqtt
    
    def execute(self) -> None:
        logging.info(f"Action: {self.command} requested for VM {self.name}")
        if (self.command == "play"):
            self.__start_vm()
        elif (self.command == "pause"):
            self.__pause_vm()
        elif (self.command == "stop"):
            self.__stop_vm()
        elif (self.command == "destroy"):
            self.__shutdown_vm()
        else:
            logging.error(f"Unknown command {self.command} for VM {self.name}")
        return
    
    def __get_domain(self) -> virDomain:
        return self.virshClient.client.lookupByName(self.name)
    
    def __stop_vm(self) -> None:
        domain = self.__get_domain()
        state, _ = domain.state()
        if (state == libvirt.VIR_DOMAIN_SHUTOFF):
            logging.error(f"Can't stop a VM ({self.name}) that's shut off.")
            return
        domain.shutdown()
        self.mqttClient.publish_vm_subject(name=self.name, subject="status", value="processing stop") 
    
    def __shutdown_vm(self) -> None:
        domain = self.__get_domain()
        state, _ = domain.state()
        if (state == libvirt.VIR_DOMAIN_SHUTOFF):
            logging.error(f"Can't shut down a VM ({self.name}) that's shut off.")
            return
        domain.destroyFlags(libvirt.VIR_DOMAIN_DESTROY_GRACEFUL)
    
    def __pause_vm(self) -> None:
        domain = self.__get_domain()
        state, _ = domain.state()
        if (state == libvirt.VIR_DOMAIN_SHUTOFF):
            logging.error(f"Can't pause a VM ({self.name}) that's shut off.")
            return
        domain.suspend()   
        self.mqttClient.publish_vm_subject(name=self.name, subject="status", value="processing pause") 
    
    def __start_vm(self) -> None:
        domain = self.__get_domain()
        state, _ = domain.state()
        
        if (state == libvirt.VIR_DOMAIN_PAUSED):
            domain.resume()
        elif (state == libvirt.VIR_DOMAIN_SHUTOFF):
            domain.create()
        else:
            obtained_state = VMStates.get_state(state)
            logging.error(f"Unsupported action play/resume on VM {self.name} on current state {obtained_state}")
            return
        self.mqttClient.publish_vm_subject(name=self.name, subject="status", value="processing start")
    