import logging, json
from typing import Callable, List
import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessageInfo

import threading
from threading import Thread

homeassistant_listen_topic = "homeassistant/button/virsh/#"

class Callback:
    listener: Callable[[str, str, any, bool], None]

class MqttClient:
    username: str
    password: str
    
    brooker: str
    brooker_port: int
    
    mqttClient: mqtt.Client
    
    mqtt_thread_stopFlag = threading.Event()
    mqtt_thread: Thread
    
    event_callback: None | Callable
    
    def __init__(self, brooker: str, port: int, username: str, password: str, event_callback: None | Callable = None) -> None:
        self.brooker = brooker
        self.brooker_port = port
        self.username = username
        self.password = password
        self.event_callback = event_callback
        
    def set_event_callback(self, event_callback: None | Callable) -> None:
        """
        This will overwrite initially defined event_callback provided in constructor
        """
        self.event_callback = event_callback
        
    def start(self) -> None:
        if (self.mqttClient.is_connected()):
            self.mqttClient.disconnect()
        if (self.mqttClient is not None):
            self.mqttClient = None
        self.mqtt_thread_stopFlag.clear()
        self.mqttClient = mqtt.Client(client_id=self.brooker, protocol=mqtt.MQTTv311, transport="tcp", callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
        if (self.password is not None):
            logging.info("Setting Username and Password for MQTT connection")
            self.mqttClient.username_pw_set(username=self.username, password=self.password)
        self.mqttClient.connect(self.brooker, self.brooker_port, 60)     
        self.mqtt_thread = Thread(target=self.__listen_to_mqtt, daemon=True)
        self.mqtt_thread.start()
    
    def stop(self) -> None:
        self.mqtt_thread_stopFlag.set()
    
    def __listen_to_mqtt(self) -> None:
        logging.info(f"MQTT Starting listening to topic: {homeassistant_listen_topic}")
        self.mqttClient.subscribe(homeassistant_listen_topic)
        self.mqttClient.on_message = self.__on_mqtt_message
        self.mqttClient.on_connect = self.__on_mqtt_connect
        self.mqttClient.on_disconnect = self.__on_mqtt_disconnect
        while not self.mqtt_thread_stopFlag.is_set():
            self.mqttClient.loop(timeout=1)  # Kjør loop med timeout
        logging.info("MQTT Thread stopped")    
        
    def __on_mqtt_connect(client, userdata, flags, rc):
        if (rc == 0):
            logging.info("MQTT Connected to server")
        else:
            logging.error("MQTT Failed to connect to server..")
        pass
    
    def __on_mqtt_disconnect(client, userdata, rc):
        if (rc != 0):
            logging.error(f"MQTT Connection were unexpected closed: {rc}")
        else:
            logging.info("MQTT Connection was closed")
    
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
            logging.debug(f"MQTT Received ==> {vm_name} and with action {action}")
            if (self.event_callback is not None):
                self.event_callback(vm_name, action)
            else:
                logging.warning("event_callback is undefined, thus events received will be lost..")


    def publish(self, topic: str | None, name: str, subject: str, value: any, callback: Callback | None) -> None:
        result: MQTTMessageInfo | None
        if (topic == None):
            result = self.mqttClient.publish(f"virsh/vm/{name}/{subject}", value, retain=True)
        else:
            result = self.mqttClient.publish()
        publish_thread = threading.Thread(target=self.__on_mqtt_publish_executed, args=(name, subject, value, result, callback))
        publish_thread.start()

    def __on_mqtt_publish_executed(self, vm_name: str, vm_subject: str, value: any, result: MQTTMessageInfo, callback: Callback | None):
        success = False
        try:
            result.wait_for_publish(timeout=30)  # Blokkerende med timeout
            logging.info("MQTT publish successful")
            success = True
        except Exception as e:
            logging.error("Failed to publish message to MQTT")
            logging.exception(e)        
        if (callback != None):
            callback.listener(vm_name, vm_subject, value, success)
        