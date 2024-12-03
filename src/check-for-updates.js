const fs = require('fs');
const core = require('@actions/core');
const { SETTING, request_http, request_https, cn_get_maintenance_status } = require('./constants');

run();
async function run() {
    const changed = await update();
    core.setOutput("success", changed);
}

function update() {
    return new Promise(async function (resolve) {
        // READ CURRENT DATABASE VERSIONS
        let current;
        const version_file = 'version.json';
        if (fs.existsSync(version_file)) {
            current = JSON.parse(fs.readFileSync(version_file, 'utf8'));
            console.log('[update] EXISTING VERSION FILE FOUND!', current);
        }
        else {
            // DATABASE VERSION FILE DOES NOT EXIST, START FROM SCRATCH
            current = {
                CN: {
                    version: SETTING.DEFAULT_TRUTH_VERSION.CN,
                    hash: "",
                    cdnAddr: "",
                },
                EN: {
                    version: SETTING.DEFAULT_TRUTH_VERSION.EN,
                    hash: "",
                },
                JP: {
                    version: SETTING.DEFAULT_TRUTH_VERSION.JP,
                    hash: "",
                },
                KR: {
                    version: SETTING.DEFAULT_TRUTH_VERSION.KR,
                    hash: "",
                    cdnAddr: "",
                },
                TH: {
                    version: SETTING.DEFAULT_TRUTH_VERSION.TH,
                    hash: "",
                },
                TW: {
                    version: SETTING.DEFAULT_TRUTH_VERSION.TW,
                    hash: "",
                },
            };
            console.log('[update] VERSION FILE NOT FOUND. USING DEFAULT VALUES... (initial setup may take a long time!)');
        }

        const promises = await Promise.all([
            update_cn(current.CN.version, current.CN.cdnAddr),
            // update_en(current.EN.version),
            update_jp(current.JP.version),
            update_kr(current.KR.version, current.KR.cdnAddr),
            // update_th(current.TH.version),
            update_tw(current.TW.version),
        ]);
        console.log("[update] UPDATE CHECK COMPLETE", promises);

        // CHECK FOR ANY CHANGES
        let changed = {};
        const result = {
            CN: promises[0],
            // EN: promises[1],
            JP: promises[1],
            KR: promises[2],
            // TH: promises[3],
            TW: promises[3],
        };
        if (current.CN.version !== result.CN.version || current.CN.cdnAddr !== result.CN.cdnAddr) {
            changed.CN = true;
        }
        // if (current.EN.version !== result.EN.version) {
        //     changed.EN = true;
        // }
        // else {
        //     // version didn't change, but what about the hash?
        //     const res = await check_hash_en(result.EN.version, current.EN.hash);
        //     if (res.success) {
        //         changed.EN = true;
        //     }
        // }
        if (current.JP.version !== result.JP.version) {
            changed.JP = true;
        }
        if (current.KR.version !== result.KR.version || current.KR.cdnAddr !== result.KR.cdnAddr) {
            changed.KR = true;
        }
        if (current.TH.version !== result.TH.version) {
            changed.TH = true;
        }
        // if (current.TW.version !== result.TW.version) {
        //     changed.TW = true;
        // }

        const is_changed = Object.keys(changed).length > 0;
        if (is_changed) {
            console.log("[update] CHANGES DETECTED, UPDATING VERSION FILE...");
            current.CN = {
                ...current.CN,
                version: result.CN.version,
                cdnAddr: result.CN.cdnAddr,
            };
            // current.EN = {
            //     ...current.EN,
            //     version: result.EN.version,
            // };
            current.JP = {
                ...current.JP,
                version: result.JP.version,
            };
            current.KR = {
                ...current.KR,
                version: result.KR.version,
                cdnAddr: result.KR.cdnAddr,
            };
            // current.TH = {
            //     ...current.TH,
            //     version: result.TH.version,
            // };
            current.TW = {
                ...current.TW,
                version: result.TW.version,
            };
            fs.writeFile(version_file, JSON.stringify(current), function (err) {
                if (err) throw err;
            });
            fs.writeFile('changed.json', JSON.stringify(changed), function (err) {
                if (err) throw err;
            });
        }
        else {
            console.log("[update] NO CHANGES DETECTED. ALL REGIONS MUST BE ON LATEST VERSION!");
        }
        resolve(is_changed);
    });
}

function update_cn(version = SETTING.DEFAULT_TRUTH_VERSION.CN, current_cdnAddr = "") {
    /*
        priconne-cn datamine notes
        - truth version can be obtained from https://le1-prod-all-gs-gzlj.bilibiligame.net/source_ini/get_maintenance_status?format=json (no need to guess)
          - needs to be a POST with the "RES-KEY" header. "RES-KEY" seems to be the same for everyone, but that might change idk
          - response also contains the CDN host
        - url to get manifest/assets are the most unique here (specifically missing region code and formatting):
          - https://<cdn_address>/Manifest/AssetBundles/<platform>/<version>/manifest/<manifest_name>_assetmanifest
          - https://<cdn_address>/pool/AssetBundles/<platform>/<first_2_characters_of_hash>/<hash>
        - maintenance can happen on server sometimes, making it impossible to get maintenance status as it will return "发生了错误。返回到标题界面。"
          - check if `data.resource` exists and if not then just return whatever CN version had last
    */
    return new Promise(async function (resolve) {
        console.log('[update_cn] CHECKING FOR DATABASE UPDATES...');

        // get truth version
        const res = await cn_get_maintenance_status();
        if (!res.data.resource) {
            console.log(`[update_cn] UNABLE TO GET MAINTENANCE STATUS, GAME UNDER MAINTENANCE? SKIPPING FOR NOW...`);
            resolve({
                version: version,
                cdnAddr: current_cdnAddr
            });
            return;
        }
        const result = {
            version: res.data.manifest_ver,
            cdnAddr: res.data.resource[0]
        };

        console.log(`[update_cn] VERSION CHECK COMPLETE ; LATEST TRUTH VERSION: ${result.version}`);
        resolve(result);
    });
}

function update_en(version = SETTING.DEFAULT_TRUTH_VERSION.EN) {
    /*
        priconne-en datamine notes
        - versioning pattern seems the same as jp, so that's cool.
        - it's possible for database to update but truth version doesn't
        - this will no longer work, priconne-en has shut down their servers as of April 30th 2023: <https://twitter.com/priconne_en/status/1652477875331932161>
    */
    return new Promise(async function (resolve) {
        console.log('[update_en] CHECKING FOR DATABASE UPDATES...');
        (async () => {
            // FIND THE NEW TRUTH VERSION
            for (let i = 1 ; i <= SETTING.TEST_MAX.EN ; i++) {
                const guess = version + (i * SETTING.TEST_MULTIPLIER);
                console.log(`[update_en] ${'[GUESS]'.padEnd(10)} ${guess}`);
                const res = await request_http(SETTING.HOST.EN,
                    `/dl/Resources/${guess}/Jpn/AssetBundles/iOS/manifest/masterdata_assetmanifest`);
                if (res.statusCode === 200) {
                    console.log(`[update_en] ${'[SUCCESS]'.padEnd(10)} ${guess} RETURNED STATUS CODE 200 (VALID TRUTH VERSION)`);

                    // RESET LOOP
                    version = guess;
                    i = 0;
                }
            }
            return {result: {version}};
        })().then(({result}) => {
            console.log(`[update_en] VERSION CHECK COMPLETE ; LATEST TRUTH VERSION: ${result.version}`);
            resolve(result);
        });
    });
}

function check_hash_en(version, hash) {
    return new Promise(async function (resolve) {
        console.log('[check_hash_en] CHECKING FOR NEW DATABASE HASH');
        (async () => {
            const {res, bundle} = await request_http(SETTING.HOST.EN, `/dl/Resources/${version}/Jpn/AssetBundles/iOS/manifest/masterdata_assetmanifest`, true);
            const new_hash = bundle.split(",")[1];
            return {result: {hash: new_hash}};
        })().then(({result}) => {
            console.log(`[check_hash_en] HASH CHECK COMPLETE ; CURRENT HASH: ${hash} ; LATEST HASH: ${result.hash}`);
            resolve({
                ...result,
                success: hash !== result.hash,
            });
        })
    });
}

function update_jp(version = SETTING.DEFAULT_TRUTH_VERSION.JP) {
    /*
        priconne-jp datamine notes
        - truth versions are incremented by 10.
        - thank goodness there's no funky patterns like other servers, im looking at you cn, kr, and tw
    */
    return new Promise(async function (resolve) {
        console.log('[update_jp] CHECKING FOR DATABASE UPDATES...');
        (async () => {
            // FIND THE NEW TRUTH VERSION
            for (let i = 1 ; i <= SETTING.TEST_MAX.JP ; i++) {
                const guess = version + (i * SETTING.TEST_MULTIPLIER);
                console.log(`[update_jp] ${'[GUESS]'.padEnd(10)} ${guess}`);
                const res = await request_http(SETTING.HOST.JP,
                    `/dl/Resources/${guess}/Jpn/AssetBundles/iOS/manifest/masterdata_assetmanifest`);
                if (res.statusCode === 200) {
                    console.log(`[update_jp] ${'[SUCCESS]'.padEnd(10)} ${guess} RETURNED STATUS CODE 200 (VALID TRUTH VERSION)`);

                    // RESET LOOP
                    version = guess;
                    i = 0;
                }
            }
            return {result: {version}};
        })().then(({result}) => {
            console.log(`[update_jp] VERSION CHECK COMPLETE ; LATEST TRUTH VERSION: ${result.version}`);
            resolve(result);
        });
    });
}

function update_kr(version = SETTING.DEFAULT_TRUTH_VERSION.KR, current_cdnAddr = "") {
    /*
        priconne-kr datamine notes
        - it seems the cdn address changes often depending on the patch.
        - luckily, this cdn address can be found in the url in fetch_host().
            - cdn url is usually formatted like patch.pcr.kakaogame.com/live/Patch####/
        - unfortunately, it seems more difficult to guess the truth version because there's larger gaps.
        - this means that it'll take longer to figure out if there's a new truth version
        - also instead of 'Jpn' like most regions, this server opts to use 'Kor'
        - any truth version, including older ones, can exist in every cdn url
        - if Patch#### changes every db update, we can assume that if cdn url doresnt change then truth version won't either
    */
    return new Promise(async function (resolve) {
        console.log('[update_kr] CHECKING FOR DATABASE UPDATES...');
        (async () => {
            const {res, bundle} = await fetch_host();
            if (res.statusCode !== 200) {
                console.log(`[update_kr] ERROR: StatusCode ${res.statusCode} ; UNABLE TO FETCH HOST ADDRESS.`);
                return {result: {version, cdnAddr: current_cdnAddr}};
            }
            const cdnAddr = JSON.parse(bundle).content.appOption.cdnAddr;

            if (cdnAddr === current_cdnAddr) {
                // cdnAddr has not changed
                console.log(`[update_kr] CDN ADDRESS HAS NOT CHANGED. ASSUMING NO DATA HAS CHANGED...`);
                return {success: true, result: {version, cdnAddr}};
            }

            // FIND THE NEW TRUTH VERSION
            const cdn_url = new URL(cdnAddr);
            for (let i = 1 ; i <= SETTING.TEST_MAX.KR ; i++) {
                const guess = version + (i * SETTING.TEST_MULTIPLIER);
                if (guess % 1000 === 0) {
                    console.log(`[update_kr] ${'[GUESS]'.padEnd(10)} ${guess} ~`);
                }
                const res = await request_http(cdn_url.hostname,
                    `${cdn_url.pathname}dl/Resources/${guess}/Kor/AssetBundles/iOS/manifest/manifest_assetmanifest`);
                if (res.statusCode === 200) {
                    console.log(`[update_kr] ${'[SUCCESS]'.padEnd(10)} ${guess} RETURNED STATUS CODE 200 (VALID TRUTH VERSION)`);

                    // RESET LOOP
                    version = guess;
                    i = 0;
                }
            }
            return {success: true, result: {version, cdnAddr}};
        })().then(({success, result}) => {
            if (success) {
                console.log(`[update_kr] VERSION CHECK COMPLETE ; LATEST TRUTH VERSION: ${result.version}`);
            }
            resolve(result);
        });
    });

    function fetch_host() {
        return new Promise(async function (resolve) {
            request_https('infodesk-zinny3.game.kakao.com',
            '/v2/app?appId=235375&appVer=2.0.11&market=googlePlay&sdkVer=3.10.2&os=android&lang=ko&osVer=6.0.1&country=kr',
            true).then((obj) => {
                resolve(obj);
            });
        });
    }
}

function update_th(version = SETTING.DEFAULT_TRUTH_VERSION.TH) {
    /*
        priconne-th datamine notes
        - versions seem to increment by 10s (similar to JP)
        - instead of "Jpn" it uses "Tha" (similar to KR)
        - versions can jump to the next 1000th version whenever
        - certain 1000 versions arent guaranteed to exist, e.g. 10000400 -> 10002000... 10001000 did not exist
        - this will no longer work, priconne-th has shut down their servers as of December 4th 2024: <https://princessconnect.i3play.com/news/view?content=notice&id=MjAyNDEwMTcxNDI1MTY>
    */
    return new Promise(async function (resolve) {
        console.log('[update_th] CHECKING FOR DATABASE UPDATES...');
        (async () => {
            // FIND THE NEW TRUTH VERSION
            for (let i = 1 ; i <= SETTING.TEST_MAX.TH ; i++) {
                const guess = version + (i * SETTING.TEST_MULTIPLIER);
                if (guess % 500 === 0) {
                    console.log(`[update_th] ${'[GUESS]'.padEnd(10)} ${guess} ~`);
                }
                const res = await request_https(SETTING.HOST.TH,
                    `/PCC/Live/dl/Resources/${guess}/Tha/AssetBundles/iOS/manifest/manifest_assetmanifest`);
                if (res.statusCode === 200) {
                    console.log(`[update_th] ${'[SUCCESS]'.padEnd(10)} ${guess} RETURNED STATUS CODE 200 (VALID TRUTH VERSION)`);

                    // RESET LOOP
                    version = guess;
                    i = 0;
                }
            }
            return {result: {version}};
        })().then(({result}) => {
            console.log(`[update_th] VERSION CHECK COMPLETE ; LATEST TRUTH VERSION: ${result.version}`);
            resolve(result);
        });
    });
}

function update_tw(version = SETTING.DEFAULT_TRUTH_VERSION.TW) {
    /*
        priconne-tw datamine notes
        - so far it seems truth versions usually start with some large digit in the 10,000s
        - numbering is incremented by 1s instead of 10s like other versions
        - occasionally, the truth version can go up by 10,000 for some reason
        - we can figure out the 10,000th digit first, then work our way to smaller numbers
        - we need to check 10,000 and 10,001 because sometimes 10,000 can not exist but 10,001 can
    */
    return new Promise(async function (resolve) {
        console.log('[update_tw] CHECKING FOR DATABASE UPDATES...');
        (async () => {
            // FIND THE NEW TRUTH VERSION
            // let guess = Math.floor(version / 10000) * 10000; // old version, resume from last known truth version
            let guess = 0; // new version, starting from scratch to prevent errors
            for (const delta of [1000000, 100000, 10000, 1000, 100, 10, 1]) {
                guess = await find_latest(guess, delta);
            }
            version = guess;

            function find_latest(guess, delta) {
                return new Promise(async (resolve) => {
                    let temp;
                    let success = true;
                    while (success) {
                        temp = next_guess(guess, delta);

                        // try guess
                        let guess_str = to_string(temp);
                        log_guess(guess_str);
                        let res = await request_https(SETTING.HOST.TW, get_path(guess_str));
                        if (res.statusCode === 200) {
                            log_success(guess_str);
                            guess = temp;
                            continue;
                        }

                        if (delta !== 1) {
                            // try guess + 1 -> ... -> guess + 5
                            let i, success = false;
                            for (i = 1 ; i < 5 ; i++) {
                                guess_str = to_string(temp + i);
                                log_guess(guess_str);
                                res = await request_https(SETTING.HOST.TW, get_path(guess_str));
                                if (res.statusCode === 200) {
                                    success = true;
                                    break;
                                }
                            }
                            if (success) {
                                log_success(guess_str);
                                guess = i;
                                continue;
                            }
                        }
                        success = false;
                    }
                    resolve(guess);
                });
                function next_guess(guess, delta) {
                    return guess + delta;
                }
                function to_string(guess) {
                    return `${guess}`.padStart(8, '0');
                }
                function get_path(guess_str) {
                    return `/dl/Resources/${guess_str}/Jpn/AssetBundles/iOS/manifest/manifest_assetmanifest`;
                }
                function log_guess(guess_str) {
                    console.log(`[update_tw] ${'[GUESS]'.padEnd(10)} ${guess_str}`);
                }
                function log_success(guess_str) {
                    console.log(`[update_tw] ${'[SUCCESS]'.padEnd(10)} ${guess_str} RETURNED STATUS CODE 200 (VALID TRUTH VERSION)`);
                }
            }
            return {success: true, result: {version}};
        })().then(({success, result}) => {
            if (success) {
                console.log(`[update_tw] VERSION CHECK COMPLETE ; LATEST TRUTH VERSION: ${result.version}`);
            }
            resolve(result);
        });
    });
}

