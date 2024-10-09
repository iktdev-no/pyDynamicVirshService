
install_location="/usr/local/dynamic-virsh-service"
service_name="dynamic-virsh-service"
service_file="$service_name.service"
package_name="pyDynamicVirshService"
vm_name_filter=()



manage_vm_name_filter() {

    while true; do
        domain_menu=$(whiptail --title "Virtual machines filter" --menu \
        "Choose action" 15 60 4 \
        "1" "Add VM Name" \
        "2" "Remove VM Name" \
        "3" "Edit VM Name" \
        "4" "Finish" 3>&1 1>&2 2>&3)

        case $domain_menu in
            "1") add_vm_name ;;
            "2") remove_vm_name ;;
            "3") edit_vm_name ;;
            "4") break ;;
            *) echo "User aborted.. Exiting.."
                exit 1 
            ;;
        esac
    done
}


add_vm_name() {
    new_vm_name=$(whiptail --inputbox "Add a new VM Name to exclusion filter:" 10 60 "" 3>&1 1>&2 2>&3)
    vm_name_filter+=("$new_vm_name")
}

# Funksjon for å fjerne domener
remove_vm_name() {
    if [ ${#vm_name_filter[@]} -eq 0 ]; then
        whiptail --msgbox "No VM Name to remove." 10 60
    else
        display_list=()
        for vm_name in "${vm_name_filter[@]}"; do
            # Lagre interface med IP-er som beskrivelse
            display_list+=("$vm_name" " " OFF)
        done

        # Bruker whiptail for å velge domener å fjerne
        remove_vm_name=$(whiptail --title "Fjern domene" --checklist "Choose VM names you want to remove:" 15 60 6 "${display_list[@]}" 3>&1 1>&2 2>&3)

        if [ -n "$remove_vm_name" ]; then
            # Fjern valgte domener fra arrayen
            for vm_name in $remove_vm_name; do
                vm_name=$(echo "$vm_name" | sed 's/"//g')  # Fjern anførselstegn
                for i in "${!vm_name_filter[@]}"; do
                    if [ "${vm_name_filter[i]}" = "$vm_name" ]; then
                        unset 'vm_name_filter[i]'  # Fjern elementet
                    fi
                done
            done
            # Fjern tomme elementer fra arrayen
            vm_name_filter=("${vm_name_filter[@]}")
        fi
    fi
}



# Funksjon for å redigere et domene
edit_vm_name() {
    if [ ${#vm_name_filter[@]} -eq 0 ]; then
        echo "Ingen domener å redigere"
        whiptail --msgbox "Ingen domener å redigere." 10 60
    else
        display_list=()
        for vm_name in "${vm_name_filter[@]}"; do
            # Lagre interface med IP-er som beskrivelse
            display_list+=("$vm_name" " ")
        done

        selected_vm_name=$(whiptail --title "Edit VM name" --menu  "Choose a VM name you want to edit:" 15 60 6 "${display_list[@]}" 3>&1 1>&2 2>&3)

        selected_vm_name=$(echo "$selected_vm_name" | sed 's/"//g')
        edited_vm_name=$(whiptail --inputbox "Edit VM name $selected_vm_name:" 10 60 "$selected_vm_name" 3>&1 1>&2 2>&3)

        # Oppdater det redigerte domenet
        for i in "${!vm_name_filter[@]}"; do
            if [ "${vm_name_filter[$i]}" == "$selected_vm_name" ]; then
                vm_name_filter[$i]=$edited_vm_name
            fi
        done
    fi
}



prerequisites() {
    echo "Installing dependencies"

    sudo apt update
    sudo apt install -y python3-pip python3-venv libvirt-dev pkg-config python3-dev
    mkdir --parents $install_location
    sudo chmod -R 0777 $install_location
    python3 -m venv "$install_location/venv"
    source "$install_location/venv/bin/activate"


    pip install $package_name -U

    if [ $? -eq 0 ]; then
        # Sjekk om versjonsnummeret har endret seg
        new_version=$(pip show $package_name | grep Version | awk '{print $2}')
        if [ "$current_version" != "$new_version" ]; then
            echo "$package_name ble oppdatert fra versjon $current_version til $new_version."
        else
            echo "$package_name var allerede på den nyeste versjonen $new_version."
        fi
    else
        echo "Feil under installasjon eller oppdatering av $package_name. Avbryter."
        exit 1
    fi

    deactivate
}


generate_json_config() {
    MQTT_HOST=$(whiptail --inputbox "Enter MQTT Host IP Address:" 8 39 --title "MQTT Host" 3>&1 1>&2 2>&3)
    MQTT_PORT=$(whiptail --inputbox "Enter MQTT Host Port:" 8 39 "1883" --title "MQTT Port" 3>&1 1>&2 2>&3)
    MQTT_USERNAME=$(whiptail --inputbox "Enter MQTT Username (optional):" 8 39 --title "MQTT Username" 3>&1 1>&2 2>&3)
    MQTT_PASSWORD=$(whiptail --passwordbox "Enter MQTT Password (optional):" 8 39 --title "MQTT Password" 3>&1 1>&2 2>&3)

    # QEMU Input (predefined but modifiable)
    QEMU_ADDRESS=$(whiptail --inputbox "Enter QEMU Address:" 8 39 "qemu:///system" --title "QEMU Address" 3>&1 1>&2 2>&3)



    if whiptail --title "VM Name Filter" --yesno "Do you want to add VM Names to exclusion list?" 10 60; then
        manage_vm_name_filter
    fi

    json_output=$(jq -n \
        --arg mqtt_host "$MQTT_HOST" \
        --argjson mqtt_port $MQTT_PORT \
        --arg mqtt_username "$MQTT_USERNAME" \
        --arg mqtt_password "$MQTT_PASSWORD" \
        --arg qemu_address "$QEMU_ADDRESS" \
        --argjson excluded_vms "$(printf '%s\n' "${vm_name_filter[@]}" | jq -R . | jq -s .)" \
        '{
            "mqtt": {
                "host": $mqtt_host,
                "port": $mqtt_port,
                "username": $mqtt_username,
                "password": $mqtt_password
            },
            "qemu": {
                "address": $qemu_address,
                "excluded_vms": $excluded_vms
            }
        }'
    )
    
    # Skriv ut eller lagre JSON
    echo "$json_output" > "$install_location/config.json"
}


setup() {

    if [ -f "$install_location/config.json" ]; then
        echo "Using existing $install_location/config.json"
    else
        generate_json_config
    fi

    systemctl stop $service_file
    systemctl disable $service_file

    rm "/etc/systemd/system/$service_file"
    systemctl daemon-reload

    echo "Creating DRU Service runner"
    cat > "$install_location/service.py" <<EOL
import signal
from DynamicVirshService import DynamicVirshService
config = "${install_location}/config.json"
service = DynamicVirshService(config)
service.start()
signal.signal(signal.SIGINT, lambda sig, frame: service.stop())
EOL


    echo "Creating Service file"
    cat > "/etc/systemd/system/$service_file" <<EOL
[Unit]
Description=Dynamic Virsh Service

[Service]
Type=simple
Restart=always
ExecStart=${install_location}/venv/bin/python -u ${install_location}/service.py
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOL

    chmod +x "$install_location/service.py"
    chown root:root "$install_location/service.py"

    systemctl daemon-reload

    systemctl enable $service_file
    systemctl start $service_file

    systemctl status $service_file

    echo "Done!"
 #   journalctl -exfu dynamic-routing-updater
    sudo chmod -R 755 $install_location

}


prerequisites
setup