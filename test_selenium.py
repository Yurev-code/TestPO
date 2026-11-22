from selenium import webdriver
from selenium.webdriver.firefox.options import Options

options = Options()
options.add_argument("--headless")
options.binary_location = "/snap/firefox/current/usr/lib/firefox/firefox"

driver = webdriver.Firefox(options=options)
driver.get("https://example.com")
print("Title:", driver.title)
driver.quit()
