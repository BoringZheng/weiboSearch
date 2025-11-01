#!/bin/bash

pyinstaller --clean --log-level=WARN --noconfirm --onefile `
  --name "智搜" `
  --icon "icon.ico" `
  --add-data "weibo;weibo" `
  --add-data "scrapy.cfg;." `
  --copy-metadata scrapy `
  --copy-metadata lxml `
  --copy-metadata parsel `
  --copy-metadata w3lib `
  --copy-metadata twisted `
  --copy-metadata "zope.interface" `
  --copy-metadata cssselect `
  --copy-metadata itemadapter `
  --copy-metadata itemloaders `
  --copy-metadata protego `
  --copy-metadata queuelib `
  --collect-submodules scrapy `
  --collect-submodules twisted `
  --hidden-import "twisted.internet.asyncioreactor" `
  --exclude-module "twisted.trial.test" `
  --exclude-module "twisted.trial._synctest" `
  run_weibo_search.py

