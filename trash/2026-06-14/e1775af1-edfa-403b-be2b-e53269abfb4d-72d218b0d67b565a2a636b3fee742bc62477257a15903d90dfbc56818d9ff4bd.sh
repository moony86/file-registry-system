#!/bin/bash

# ============================================================
# ⚡ NET MANAGER PRO v3.1 - Enhanced with Disconnect Features
# ============================================================

# ====== ألوان ورموز ======
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
CHECK="✔️"
WARN="⚠️"

CACHE_WIFI="/tmp/netmanager_wifi.cache"
CACHE_BT="/tmp/netmanager_bt.cache"

# ====== دوال مساعدة ======
print_header() {
    clear
    echo -e "${BLUE}==========================================${NC}"
    echo -e "${CYAN}        ⚡ NET MANAGER PRO v3.1 ⚡        ${NC}"
    echo -e "${BLUE}==========================================${NC}"
}

check_deps() {
    for tool in nmcli bluetoothctl awk sed; do
        if ! command -v $tool &>/dev/null; then
            echo -e "${RED}${WARN} خطأ: أداة $tool غير مثبتة.${NC}"
            exit 1
        fi
    done
}

# ====== إدارة WiFi ======
wifi_menu() {
    while true; do
        print_header
        echo -e "${YELLOW}🔍 جاري فحص الشبكات...${NC}"
        nmcli dev wifi rescan &>/dev/null

        mapfile -t networks < <(nmcli -t -f SSID,SIGNAL dev wifi | awk -F: '$1!="" {print $1":"$2}' | sort -t: -u -k1,1 | sort -rn -t: -k2 | head -n 20)

        if [ ${#networks[@]} -eq 0 ]; then
            echo -e "${RED}لا توجد شبكات${NC}"
            read -p "اضغط Enter للعودة..."
            return
        fi

        echo -e "ID | SSID | قوة الإشارة | حالة الاتصال | محفوظ"
        echo -e "-- | ---- | ----------- | ----------- | ------"
        wifi_now=$(nmcli -t -f active,ssid dev wifi | grep '^yes' | cut -d: -f2)

        for i in "${!networks[@]}"; do
            ssid=$(echo "${networks[$i]}" | cut -d: -f1)
            signal=$(echo "${networks[$i]}" | cut -d: -f2)
            saved=$(nmcli connection show | grep -w "$ssid" &>/dev/null && echo "✔️" || echo "-")
            connected=$( [ "$ssid" == "$wifi_now" ] && echo -e "${GREEN}متصل${NC}" || echo "-" )
            printf "[%d] | %s | %s%% | %s | %s\n" $((i+1)) "$ssid" "$signal" "$connected" "$saved"
        done

        echo -e "\n${CYAN}[r] تحديث | [d] فصل الحالي | [b] عودة | [الرقم] للاتصال/الفصل${NC}"
        read -p "Selection: " choice

        case $choice in
            r|R) continue ;;
            b|B) break ;;
            d|D) 
                if [ -n "$wifi_now" ]; then
                    echo -e "${RED}جاري فصل $wifi_now...${NC}"
                    nmcli device disconnect wlan0 &>/dev/null || nmcli device disconnect $(nmcli device | grep wifi | awk '{print $1}')
                else
                    echo -e "${YELLOW}لا يوجد اتصال نشط لفصله.${NC}"
                fi
                sleep 1
                ;;
            [0-9]*)
                idx=$((choice-1))
                if [ $idx -lt ${#networks[@]} ] && [ $idx -ge 0 ]; then
                    ssid=$(echo "${networks[$idx]}" | cut -d: -f1)
                    if [ "$ssid" == "$wifi_now" ]; then
                        read -p "أنت متصل بـ $ssid بالفعل. هل تريد الفصل؟ (y/n): " confirm
                        if [[ $confirm == [yY] ]]; then
                            nmcli device disconnect wlan0 &>/dev/null || nmcli device disconnect $(nmcli device | grep wifi | awk '{print $1}')
                        fi
                    else
                        echo -e "${YELLOW}جاري الاتصال بـ $ssid...${NC}"
                        if nmcli connection show "$ssid" &>/dev/null; then
                            nmcli connection up "$ssid"
                        else
                            read -s -p "كلمة المرور: " pass
                            echo ""
                            nmcli dev wifi connect "$ssid" password "$pass"
                        fi
                    fi
                    sleep 1
                fi
                ;;
        esac
    done
}

# ====== إدارة البلوتوث ======
bt_menu() {
    while true; do
        print_header
        echo -e "${YELLOW}📡 جاري فحص البلوتوث...${NC}"
        bluetoothctl power on >/dev/null
        # فحص سريع لمدة ثانيتين
        bluetoothctl scan on & sleep 2 && kill $! &>/dev/null

        mapfile -t bt_devs < <(bluetoothctl devices)

        if [ ${#bt_devs[@]} -eq 0 ]; then
            echo -e "${RED}لا توجد أجهزة متوفرة${NC}"
            read -p "اضغط Enter للعودة..."
            return
        fi

        echo -e "ID | MAC | NAME | مقترن | متصل"
        echo -e "-- | --- | ---- | ------ | -----"

        for i in "${!bt_devs[@]}"; do
            mac=$(echo "${bt_devs[$i]}" | awk '{print $2}')
            name=$(echo "${bt_devs[$i]}" | cut -d ' ' -f3-)
            paired=$(bluetoothctl info "$mac" | grep "Paired: yes" &>/dev/null && echo "✔️" || echo "-")
            connected=$(bluetoothctl info "$mac" | grep "Connected: yes" &>/dev/null && echo -e "${GREEN}✔️${NC}" || echo "-")
            printf "[%d] | %s | %s | %s | %s\n" $((i+1)) "$mac" "$name" "$paired" "$connected"
        done

        echo -e "\n${CYAN}[r] تحديث | [b] عودة | [الرقم] للاتصال أو الفصل${NC}"
        read -p "Selection: " choice

        case $choice in
            r|R) continue ;;
            b|B) break ;;
            [0-9]*)
                idx=$((choice-1))
                if [ $idx -lt ${#bt_devs[@]} ] && [ $idx -ge 0 ]; then
                    mac=$(echo "${bt_devs[$idx]}" | awk '{print $2}')
                    is_connected=$(bluetoothctl info "$mac" | grep "Connected: yes")
                    
                    if [ -n "$is_connected" ]; then
                        echo -e "${RED}الجهاز متصل. جاري قطع الاتصال بـ $mac...${NC}"
                        bluetoothctl disconnect "$mac"
                    else
                        echo -e "${YELLOW}جاري الاقتران والاتصال بـ $mac...${NC}"
                        bluetoothctl pair "$mac"
                        bluetoothctl trust "$mac"
                        bluetoothctl connect "$mac"
                    fi
                    sleep 1
                fi
                ;;
        esac
    done
}

# ====== القائمة الرئيسية ======
main_menu() {
    check_deps
    while true; do
        print_header
        wifi_now=$(nmcli -t -f active,ssid dev wifi | grep '^yes' | cut -d: -f2)
        bt_power=$(bluetoothctl show | grep "Powered:" | awk '{print $2}')

        echo -e "🌐 WiFi: ${GREEN}${wifi_now:-غير متصل}${NC}"
        echo -e "🔹 Bluetooth: ${BLUE}${bt_power:-off}${NC}"
        echo -e "------------------------------------------"
        echo -e "1) 📶 WiFi Manager"
        echo -e "2) 🎧 Bluetooth Manager"
        echo -e "3) ❌ خروج"
        echo -e "------------------------------------------"
        read -p "اختر (1-3): " choice

        case $choice in
            1) wifi_menu ;;
            2) bt_menu ;;
            3) echo -e "${GREEN}وداعاً!${NC}"; exit 0 ;;
            *) echo -e "${RED}خيار خاطئ!${NC}"; sleep 1 ;;
        esac
    done
}

main_menu
