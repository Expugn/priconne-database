# priconne-database

## Information
This repository serves multiple regions of `master.db` from the game Princess Connect! Re:Dive.

Updating is done automatically through GitHub Actions. Updates will be checked every hour on the 45th minute.

## Supported Regions
- China (`master_cn.db`)
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_cn.db)
- ~~English~~ (`master_en.db`)
  - English server has ended service as of `April 30, 2023 (UTC)`.
    - <https://twitter.com/priconne_en/status/1652477875331932161>
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_en.db)
- Japan (`master_jp.db`)
  - As of `10053000`, database table and column names are obfuscated
    - Use `10052900` for the last known readable database
      - [Download `10052900`](https://github.com/Expugn/priconne-database/raw/cbe012cf3e6a88ba20ce92099762eb3ea2b971e7/master_jp.db)
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_jp.db)
- Korea (`master_kr.db`)
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_kr.db)
- Taiwan (`master_tw.db`)
  - As of `00190002`, database table and column names are obfuscated
    - Use `00180024` for the last known readable database
      - [Download `00180024`](https://github.com/Expugn/priconne-database/raw/c55a2de6a973f98fd1486808779272a279f89458/master_tw.db)
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_tw.db)
- Thailand (`master_th.db`)
  - [Download](https://raw.githubusercontent.com/Expugn/priconne-database/master/master_th.db)

## Workflow
The workflow can be found in `.github/workflows/priconne-database.yml`, but the process is as such:
1. Check for updates (`src/check-for-updates.js`)
2. Download databases if updates are found (`src/download-database.js`)
3. Upload to Git

## Formatted Data Files
If you want to examine the data in the database files without downloading or figuring out how to open a `.db`/SQLite file:<br/>
<https://github.com/Expugn/priconne-diff>

## Other Stuff
This is a non-profit fan project with the purpose of practice and entertainment.<br/>
All assets belong to their respective owners.

**Project** began on March 3, 2022.
