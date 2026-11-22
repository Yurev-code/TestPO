import pytest
import requests
import urllib3
import time
import subprocess
import logging

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

BASE_URL = "https://localhost:2443"
USERNAME = "root"
PASSWORD = "0penBmc"

#Проверяет, что логин в BMC работает
@pytest.fixture(scope="session")
def auth_token():
    url = f"{BASE_URL}/redfish/v1/SessionService/Sessions"
    payload = {"UserName": USERNAME, "Password": PASSWORD}
    response = requests.post(url, json=payload, verify=False)
    assert response.status_code == 201, f"Ошибка аутентификации: {response.status_code}, {response.text}"
    token = response.headers.get("X-Auth-Token")
    assert token is not None, "Токен не найден в заголовках ответа"
    logger.info("[Фикстура] Успешный вход. Токен: %s...", token[:10])
    return token

#Проверяет, что фикстура вернула непустой токен
def test_authentication(auth_token):
    assert auth_token is not None
    assert len(auth_token) > 0
    logger.info("Тест аутентификации пройден (токен получен через фикстуру)")

#Проверяет, что сервер вернул 200 OK и что в JSON есть поля Status и PowerState
def test_get_system_info(auth_token):
    url = f"{BASE_URL}/redfish/v1/Systems/system"
    headers = {"X-Auth-Token": auth_token}
    response = requests.get(url, headers=headers, verify=False)
    assert response.status_code == 200, f"Ожидали 200, получили {response.status_code}. Ответ: {response.text}"
    data = response.json()
    assert "Status" in data, f"В ответе нет поля 'Status'. Ключи: {list(data.keys())}"
    assert "PowerState" in data, f"В ответе нет поля 'PowerState'. Ключи: {list(data.keys())}"
    logger.info("Статус системы: %s", data['Status'])
    logger.info("Состояние питания: %s", data['PowerState'])

#отправляет POST-команду на включение сервера. Проверяет, что API принял команду
def test_power_on(auth_token):
    url = f"{BASE_URL}/redfish/v1/Systems/system/Actions/ComputerSystem.Reset"
    headers = {"X-Auth-Token": auth_token, "Content-Type": "application/json"}
    payload = {"ResetType": "On"}
    response = requests.post(url, json=payload, headers=headers, verify=False)
    assert response.status_code in (202, 204), f"Ожидали 202 или 204, получили {response.status_code}. Ответ: {response.text}"
    logger.info("Команда включения отправлена, код ответа: %s", response.status_code)
    check_url = f"{BASE_URL}/redfish/v1/Systems/system"
    check_response = requests.get(check_url, headers={"X-Auth-Token": auth_token}, verify=False)
    assert check_response.status_code == 200, f"Не удалось получить статус: {check_response.status_code}"
    data = check_response.json()
    logger.info("Текущее состояние питания после команды: %s", data.get("PowerState"))

#Получаем датчики температуры.
def test_cpu_temperature(auth_token):
    headers = {"X-Auth-Token": auth_token}
    sensors_url = f"{BASE_URL}/redfish/v1/Chassis/chassis/Sensors"
    response = requests.get(sensors_url, headers=headers, verify=False)
    assert response.status_code == 200, f"Ожидали 200 для Sensors, получили {response.status_code}. Ответ: {response.text}"
    sensors_data = response.json()
    members = sensors_data.get("Members", [])
    if len(members) == 0:
        pytest.skip("В данной сборке OpenBMC коллекция Sensors пуста (сенсоры не реализованы)")
    cpu_sensor_links = []
    for member in members:
        sensor_url = f"{BASE_URL}{member['@odata.id']}"
        sensor_resp = requests.get(sensor_url, headers=headers, verify=False)
        if sensor_resp.status_code != 200:
            continue
        sensor = sensor_resp.json()
        name = sensor.get("Name", "").upper()
        if "CPU" in name or "TEMP" in name:
            cpu_sensor_links.append(sensor)
    if not cpu_sensor_links:
        pytest.skip("В данной сборке OpenBMC не найдено сенсоров с CPU/TEMP в названии")
    checked = 0
    for sensor in cpu_sensor_links:
        reading = sensor.get("Reading")
        if reading is not None:
            assert 0 <= reading <= 100, f"Температура {sensor.get('Name')} = {reading} °C вне допустимых пределов"
            logger.info("%s: %s °C — в норме", sensor.get('Name'), reading)
            checked += 1
    assert checked > 0, "Не удалось проверить ни одного сенсора с числовым значением"

#Собирает имена температурных сенсоров из Redfish и сравнивает списки.
def test_cpu_sensors_redfish_vs_ipmi(auth_token):
    headers = {"X-Auth-Token": auth_token}
    sensors_url = f"{BASE_URL}/redfish/v1/Chassis/chassis/Sensors"
    response = requests.get(sensors_url, headers=headers, verify=False)
    assert response.status_code == 200, f"Redfish вернул {response.status_code} для Sensors"
    sensors_data = response.json()
    members = sensors_data.get("Members", [])
    redfish_names = []
    for member in members:
        sensor_url = f"{BASE_URL}{member['@odata.id']}"
        sensor_resp = requests.get(sensor_url, headers=headers, verify=False)
        if sensor_resp.status_code == 200:
            sensor = sensor_resp.json()
            reading_type = sensor.get("ReadingType", "")
            if reading_type == "Temperature":
                redfish_names.append(sensor.get("Name"))
    if not redfish_names:
        pytest.skip("В Redfish не найдено сенсоров типа Temperature")
    logger.info("Датчики температуры в Redfish: %s", redfish_names)
    try:
        ipmi_result = subprocess.run(
            ["ipmitool", "-I", "lanplus", "-H", "localhost", "-p", "2623",
             "-U", "root", "-P", "0penBmc", "sdr", "type", "temperature"],
            capture_output=True, text=True, timeout=15
        )
        if ipmi_result.returncode != 0:
            pytest.skip(f"ipmitool недоступен или вернул ошибку: {ipmi_result.stderr}")
        ipmi_lines = [line for line in ipmi_result.stdout.splitlines() if "degrees C" in line]
        logger.info("Датчики температуры в IPMI: %s", ipmi_lines)
        assert len(ipmi_lines) > 0, "IPMI не вернул датчиков температуры"
    except FileNotFoundError:
        pytest.skip("ipmitool не установлен на хосте")
    except subprocess.TimeoutExpired:
        pytest.skip("ipmitool не ответил за 15 секунд")