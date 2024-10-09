import logging, json
from enum import Enum
from typing import List, Optional
import paho.mqtt.client as mqtt
import threading
from threading import Thread
from .version import __version__

from .hassConfig import HassConfig
import libvirt
from libvirt import virConnect, virDomain
from .virshClient import VirshClient, VirshVM, VMStates

logging.basicConfig(level=logging.INFO)

class DynamicVirshService:
    qemu_address: str
    qemu_excluded_vms: List[str]
    
    mqtt_username: str
    mqtt_password: str
    
    mqtt_brooker: str
    mqtt_brooker_port: int
    
    mqttClient: mqtt.Client
    virshClient: VirshClient | None
    mqtt_thread_stopFlag = threading.Event()
    mqtt_thread: Thread


    __vms_pushed: List[str] = []

    def __init__(self, configFile: str) -> None:
        self.virshClient = None
        logging.info(f"Version: {__version__}")
        config: dict = json.load(open(configFile))
        mqttConfig: dict = config["mqtt"]
        self.mqtt_brooker = mqttConfig["host"]
        self.mqtt_brooker_port = mqttConfig.get("port", 1883)
        self.mqtt_username = mqttConfig.get("username", None)
        self.mqtt_password = mqttConfig.get("password", None)
        
        qemuConfig: dict = config["qemu"]
        self.qemu_address = qemuConfig.get("address", "qemu:///system")
        self.qemu_excluded_vms = qemuConfig.get("excluded_vms", [])
        logging.info(f"VMs in exclusion list are: {",".join(self.qemu_excluded_vms)}")

        self.mqttClient = mqtt.Client(client_id=self.mqtt_brooker, protocol=mqtt.MQTTv311, transport="tcp", callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
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
            self.virshClient = VirshClient(self.qemu_address, self.__virsh_state_update)


    def is_excluded(self, name: str) -> bool:
        for excludedName in self.qemu_excluded_vms:
            if (excludedName.strip().lower() == name.strip().lower()):
                logging.info(f"VM {name} is excluded")
                return True
            else:
                logging.debug(f"VM: {name} does not match excluded: {excludedName}")
        return False

    def start(self) -> None:
        if (self.mqtt_password is not None):
            logging.info("Providing username and password for MQTT")
            self.mqttClient.username_pw_set(username=self.mqtt_username, password=self.mqtt_password)
        self.mqttClient.connect(self.mqtt_brooker, self.mqtt_brooker_port, 60)        
        
        for vm in self.virshClient.get_vms():
            self.__vms_pushed.append(vm.name)
            
            if (self.is_excluded(vm.name) == False):
                
                hassConfig = HassConfig(mqttClient=self.mqttClient)
                hassConfig.publish_sensor_config(name=vm.name, sensor_name=f"Status", subject="status")
                hassConfig.publish_binary_sensor_config(name=vm.name, sensor_name=f"Powered", subject="running")
            
                self.mqtt_publish(vm.name, "status", vm.state)
                self.mqtt_publish(vm.name, "running", "true" if vm.state != "shut off" else "false")

        self.virshClient.start()
        self.mqtt_thread_stopFlag.clear()
        self.mqtt_thread = Thread(target=self.__listen_to_mqtt, daemon=True)
        self.mqtt_thread.start()

    def stop(self) -> None:
        self.virshClient.stop()
        self.mqtt_thread_stopFlag.set()

    def __virsh_state_update(self, vmInfo: VirshVM):
        """
        Push data to mqtt
        """
        if (self.is_excluded(vmInfo.name) == False):
            if (vmInfo.name not in self.__vms_pushed):
                hassConfig = HassConfig(mqttClient=self.mqttClient)
                hassConfig.publish_sensor_config(name=vmInfo.name, sensor_name=f"{vmInfo.name} Status", subject="status")
                hassConfig.publish_binary_sensor_config(name=vmInfo.name, sensor_name=f"{vmInfo.name} Running", subject="running")
                self.__vms_pushed.append(vmInfo.name)
                
            self.mqtt_publish(vmInfo.name, "status", vmInfo.state)
            self.mqtt_publish(vmInfo.name, "running", "true" if vmInfo.state != "shut off" else "false")
            
    def __listen_to_mqtt(self) -> None:
        topic = "homeassistant/button/virsh/#"
        logging.info(f"MQTT Starting listening to topic: {topic}")
        self.mqttClient.subscribe(topic)
        self.mqttClient.on_message = self.__on_mqtt_message
        
        while not self.mqtt_thread_stopFlag.is_set():
            self.mqttClient.loop(timeout=1)  # Kjør loop med timeout
        logging.info("MQTT Thread stopped")
    
    def __on_mqtt_message(self, client, userdata, msg) -> None:
        # Hent vm_name fra topic
        topic_parts = msg.topic.split("/")
        
        topic_end = topic_parts[-1]
        if (topic_end == "set"):
            logging.debug(f"Accepted: {topic_end} from {msg.topic}")
        else:
            logging.debug(f"Ignored: {topic_end} from {msg.topic}")
        
        if len(topic_parts) >= 5 and topic_end == "set":  # Sjekk at vi har nok deler
            vm_name = topic_parts[3]  # Juster indeksen basert på strukturen i topic
            action = msg.payload.decode()  # Anta at meldingen er en enkel kommando
            logging.debug(f"VM Name: {vm_name} -> Action: {action}")
            virshCommand = VirshCommand(self.virshClient, vm_name, action)
            try:
                virshCommand.execute()
            except Exception as e:
                logging.error("An error occured while trying to executa a virsh command!")
                logging.exception(e)
                self.__connect_to_virsh()




    def mqtt_publish(self, name: str, subject: str, value: any) -> None:
        self.mqttClient.publish(f"virsh/vm/{name}/{subject}", value, retain=True)

class VirshCommand():
    virshClient: VirshClient
    name: str
    command: str
    def __init__(self, client: VirshClient, name: str, command: str) -> None:
        self.name = name
        self.command = command
        self.virshClient = client
    
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
