# priconne-database

## Information
This repository serves multiple regions of `master.db` from the game Princess Connect! Re:Dive.

Updating is done automatically through GitHub Actions. Updates will be checked every hour on the 45th minute.

## Supported Regions
- China (`master_cn.db`)
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_cn.db)
- English (`master_en.db`)
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_en.db)
- Japan (`master_jp.db`)
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_jp.db)
- Korea (`master_kr.db`)
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_kr.db)
- Taiwan (`master_tw.db`)
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_tw.db)

## Workflow
The workflow can be found in `.github/workflows/priconne-database.yml`, but the process is as such:
1. Check for updates (`src/check-for-updates.js`)
2. Download databases if updates are found (`src/download-database.js`)
3. Upload to Git

## Other Stuff
This is a non-profit fan project with the purpose of practice and entertainment.<br/>
All assets belong to their respective owners.

**Project** began on March 3, 2022.