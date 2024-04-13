const http = require('http');
const https = require('https');
const fs = require('fs');
const { exec } = require('child_process');
const core = require('@actions/core');
const { SETTING } = require('./constants');

const CHANGED = fs.existsSync('changed.json') ? JSON.parse(fs.readFileSync('changed.json', 'utf8')) : {};
const diff = {};

run();
async function run() {
    const success = await download();
    if (success) {
        console.log('[download] PROCESS COMPLETED SUCCESSFULLY!');

        let diff_str = "";
        for (const key of Object.keys(diff)) {
            diff_str += `${key}: ${`${diff[key][0]}`.padEnd(8)} -> ${diff[key][1]}\n`;
        }

        core.setOutput("title", `${Object.keys(CHANGED)}`);
        core.setOutput("diff", diff_str);
    }
    else {
        core.error('[download] FAILED, THERE ARE MISSING DATABASE FILES OR NO VERSION FILE EXISTS.');
    }
}

function download() {
    return new Promise(async function (resolve) {
        let current;
        const version_file = 'version.json';
        if (!fs.existsSync(version_file)) {
            console.log('[download] VERSION FILE NOT FOUND. PROCESS CAN NOT CONTINUE. (check for updates first!)');
            resolve();
            return;
        }
        current = JSON.parse(fs.readFileSync(version_file, 'utf8'));
        console.log('[download] EXISTING VERSION FILE FOUND!', current);

        const promises = await Promise.all([
            download_cn(current.CN.version, current.CN.cdnAddr, current.CN.hash),
            // download_en(current.EN.version, current.EN.hash),
            download_jp(current.JP.version, current.JP.hash),
            download_kr(current.KR.version, current.KR.cdnAddr, current.KR.hash),
            download_th(current.TH.version, current.TH.hash),
            download_tw(current.TW.version, current.TW.hash),
        ]);

        const result = {
            CN: promises[0],
            // EN: promises[1],
            JP: promises[1],
            KR: promises[2],
            TH: promises[3],
            TW: promises[4],
        };

        // update hashes in version file
        for (const key of Object.keys(result)) {
            if (result[key].success) {
                current[key].hash = result[key].hash;
            }
        }
        fs.writeFile(version_file, JSON.stringify(current), function (err) {
            if (err) throw err;
        });
        resolve(fs.existsSync(`${SETTING.FILE_NAME.CN}.db`)
        //     && fs.existsSync(`${SETTING.FILE_NAME.EN}.db`)
            && fs.existsSync(`${SETTING.FILE_NAME.JP}.db`)
            && fs.existsSync(`${SETTING.FILE_NAME.KR}.db`)
            && fs.existsSync(`${SETTING.FILE_NAME.TH}.db`)
            && fs.existsSync(`${SETTING.FILE_NAME.TW}.db`));
    });
}

function download_cn(version, cdnAddr, hash) {
    /*
        priconne-cn database notes
        - masterdata is not encrypted, can use UnityPack to deserialize
    */
    return new Promise(async function (resolve) {
        if (!CHANGED.CN) {
            resolve({});
            return;
        }
        if (!version || !cdnAddr || hash === undefined) {
            console.log("[download_cn] VERSION, CDN ADDRESS, OR HASH NOT PROVIDED.");
            resolve({});
            return;
        }
        console.log("[download_cn] DOWNLOADING DATABASE...");

        const name_unity3d = `${SETTING.FILE_NAME.CN}.unity3d`;
        const name = `${SETTING.FILE_NAME.CN}.db`;
        let manifest_assetmanifest = "";
        let masterdata_path = "";
        let bundle = "";

        // get masterdata path first (we don't know if it's masterdata, masterdata2, etc)
        https.get(`https://${cdnAddr}Manifest/AssetBundles/iOS/${version}/manifest/manifest_assetmanifest`, (res) => {
            res.on('data', function(chunk) {
                manifest_assetmanifest += Buffer.from(chunk).toString();
            });
            res.on('end', () => {
                masterdata_path = find_masterdata(manifest_assetmanifest);
                dl();
            });
        }).end();

        // called after masterdata path is found
        function dl() {
            https.get(`https://${cdnAddr}Manifest/AssetBundles/iOS/${version}/${masterdata_path}`, (res) => {
                res.on('data', function(chunk) {
                    bundle += Buffer.from(chunk).toString();
                });
                res.on('end', () => {
                    const b = bundle.split(',');
                    const latest_hash = b[1];
                    if (latest_hash !== hash) {
                        console.log("[download_cn] DATABASE CHANGES FOUND! DOWNLOADING...");
                        diff.CN = [hash, latest_hash];
                        const file = fs.createWriteStream(name_unity3d);
                        https.get(`https://${cdnAddr}pool/AssetBundles/iOS/${latest_hash.substring(0, 2)}/${latest_hash}`, function(response) {
                            const stream = response.pipe(file);
                            stream.on('finish', () => {
                                const { PythonShell } = require('python-shell');
                                PythonShell.run('src/deserialize.py', { args: ["CN", name_unity3d, name] }, function(err) {
                                    if (err) throw err;
                                    console.log(`[download_cn] DOWNLOADED AND CONVERTED DATABASE [${latest_hash}] ; SAVED AS ${name}`);
                                    resolve({success: true, hash: latest_hash});
                                });
                            });
                        });
                    }
                    else {
                        console.log('[download_cn] DATABASE UP TO DATE!');
                        resolve({});
                    }
                });
            }).end();
        }
    });
}

function download_en(version, hash) {
    /*
        priconne-en database notes
        - masterdata is not encrypted, can use UnityPack to deserialize.
        - this will no longer work, priconne-en has shut down their servers as of April 30th 2023: <https://twitter.com/priconne_en/status/1652477875331932161>
    */
    return new Promise(async function (resolve) {
        if (!CHANGED.EN) {
            resolve({});
            return;
        }
        if (!version || hash === undefined) {
            console.log("[download_en] VERSION OR HASH NOT PROVIDED.");
            resolve({});
            return;
        }
        console.log("[download_en] DOWNLOADING DATABASE...");
        const name_unity3d = `${SETTING.FILE_NAME.EN}.unity3d`;
        const name = `${SETTING.FILE_NAME.EN}.db`;
        let manifest_assetmanifest = "";
        let masterdata_path = "";
        let bundle = "";

        // get masterdata path first (we don't know if it's masterdata, masterdata2, etc)
        http.request({
            host: SETTING.HOST.EN,
            path: `/dl/Resources/${version}/Jpn/AssetBundles/iOS/manifest/manifest_assetmanifest`,
            method: 'GET',
        }, (res) => {
            res.on('data', function(chunk) {
                manifest_assetmanifest += Buffer.from(chunk).toString();
            });
            res.on('end', () => {
                masterdata_path = find_masterdata(manifest_assetmanifest);
                dl();
            });
        }).end();

        // called after masterdata path is found
        function dl() {
            http.request({
                host: SETTING.HOST.EN,
                path: `/dl/Resources/${version}/Jpn/AssetBundles/iOS/${masterdata_path}`,
                method: 'GET',
            }, (res) => {
                res.on('data', function(chunk) {
                    bundle += Buffer.from(chunk).toString();
                });
                res.on('end', () => {
                    const b = bundle.split(',');
                    const latest_hash = b[1];

                    // DOWNLOAD FILES
                    if (hash !== latest_hash) {
                        console.log("[download_en] DATABASE CHANGES FOUND! DOWNLOADING...");
                        diff.EN = [hash, latest_hash];
                        const file = fs.createWriteStream(name_unity3d);
                        http.get(`http://${SETTING.HOST.EN}/dl/pool/AssetBundles/${latest_hash.substring(0, 2)}/${latest_hash}`, function(response) {
                            const stream = response.pipe(file);
                            stream.on('finish', () => {
                                // CONVERT .unity3d TO .db
                                const { PythonShell } = require('python-shell');
                                PythonShell.run('src/deserialize.py', { args: ["EN", name_unity3d, name] }, function(err) {
                                    if (err) throw err;
                                    console.log(`[download_en] DOWNLOADED AND CONVERTED DATABASE [${latest_hash}] ; SAVED AS ${name}`);
                                    resolve({success: true, hash: latest_hash});
                                });
                            });
                        });
                    }
                    else {
                        console.log('[download_en] DATABASE UP TO DATE!');
                        resolve({});
                    }
                });
            }).end();
        }
    });
}

function download_jp(version, hash) {
    /*
        priconne-jp database notes
        - masterdata is encrypted, needs Coneshell_call to decrypt.
        - 04/01/2024 - Coneshell_call no longer needed? Format seems to have changed to Unity3D file, or not idk
        - 04/06/2024 - nevermind about 04/01/2024's note, still needs Coneshell_call.
    */
    return new Promise(async function (resolve) {
        if (!CHANGED.JP) {
            resolve({});
            return;
        }
        if (!version || hash === undefined) {
            console.log("[download_jp] VERSION OR HASH NOT PROVIDED.");
            resolve({});
            return;
        }
        console.log("[download_jp] DOWNLOADING DATABASE...");
        const name_cdb = `${SETTING.FILE_NAME.JP}.cdb`;
        const name = `${SETTING.FILE_NAME.JP}.db`;
        let manifest_assetmanifest = "";
        let masterdata_path = "";
        let bundle = "";

        // get masterdata path first (we don't know if it's masterdata, masterdata2, etc)
        http.request({
            host: SETTING.HOST.JP,
            path: `/dl/Resources/${version}/Jpn/AssetBundles/iOS/manifest/manifest_assetmanifest`,
            method: 'GET',
        }, (res) => {
            res.on('data', function(chunk) {
                manifest_assetmanifest += Buffer.from(chunk).toString();
            });
            res.on('end', () => {
                masterdata_path = find_masterdata(manifest_assetmanifest);
                dl();
            });
        }).end();

        // called after masterdata path is found
        function dl() {
            http.request({
                host: SETTING.HOST.JP,
                path: `/dl/Resources/${version}/Jpn/AssetBundles/iOS/${masterdata_path}`,
                method: 'GET',
            }, (res) => {
                res.on('data', function(chunk) {
                    bundle += Buffer.from(chunk).toString();
                });
                res.on('end', () => {
                    const b = bundle.split(',');
                    // 04/01/2024 - latest hash moved from b[1] to b[2]
                    // 04/04/2024 - latest hash reverted back to b[1], still needs Coneshell_call
                    // 04/13/2024 - latest hash moved to b[2] again, idk
                    const latest_hash = (b[2] === "every") ? b[1] : b[2];

                    if (latest_hash !== hash) {
                        console.log("[download_jp] DATABASE CHANGES FOUND! DOWNLOADING...");
                        diff.JP = [hash, latest_hash];
                        const file = fs.createWriteStream(name_cdb);
                        http.get(`http://${SETTING.HOST.JP}/dl/pool/AssetBundles/${latest_hash.substring(0, 2)}/${latest_hash}`, function(response) {
                            const stream = response.pipe(file);
                            stream.on('finish', () => {
                                // CONVERT CDB TO DB
                                exec(`${__dirname}/vendor/coneshell/Coneshell_call.exe -cdb ${name_cdb} ${name}`, (error, stdout, stderr) => {
                                    if (error) {
                                        // 04/01/2024 - try deserializing instead
                                        const { PythonShell } = require('python-shell');
                                        PythonShell.run('src/deserialize.py', { args: ["JP", name_cdb, name] }, function(err) {
                                            if (err) throw err;
                                            console.log(`[download_jp] DOWNLOADED AND CONVERTED DATABASE (DESERIALIZE) [${latest_hash}] ; SAVED AS ${name}`);
                                            resolve({success: true, hash: latest_hash});
                                        });
                                        return;
                                    }
                                    if (stderr) throw stderr;
                                    console.log(`[download_jp] DOWNLOADED AND CONVERTED DATABASE (CONESHELL) [${latest_hash}] ; SAVED AS ${name}`);
                                    resolve({success: true, hash: latest_hash});
                                });
                            });
                        });
                    }
                    else {
                        console.log('[download_jp] DATABASE UP TO DATE!');
                        resolve({});
                    }
                });
            }).end();
        }
    });
}

function download_kr(version, cdnAddr, hash) {
    /*
        priconne-kr database notes
        - masterdata is not encrypted, can use UnityPack to deserialize.
    */
    return new Promise(async function (resolve) {
        if (!CHANGED.KR) {
            resolve({});
            return;
        }
        if (!version || hash === undefined) {
            console.log("[download_kr] VERSION, CDN ADDRESS, OR HASH NOT PROVIDED.");
            resolve({});
            return;
        }
        console.log("[download_kr] DOWNLOADING DATABASE...");
        const name_unity3d = `${SETTING.FILE_NAME.KR}.unity3d`;
        const name = `${SETTING.FILE_NAME.KR}.db`;
        let manifest_assetmanifest = "";
        let masterdata_path = "";
        let bundle = "";

        // get masterdata path first (we don't know if it's masterdata, masterdata2, etc)
        http.get(`${cdnAddr}dl/Resources/${version}/Kor/AssetBundles/iOS/manifest/manifest_assetmanifest`, (res) => {
            res.on('data', function(chunk) {
                manifest_assetmanifest += Buffer.from(chunk).toString();
            });
            res.on('end', () => {
                masterdata_path = find_masterdata(manifest_assetmanifest);
                dl();
            });
        }).end();

        // called after masterdata path is found
        function dl() {
            http.get(`${cdnAddr}dl/Resources/${version}/Kor/AssetBundles/iOS/${masterdata_path}`, (res) => {
                res.on('data', function(chunk) {
                    bundle += Buffer.from(chunk).toString();
                });
                res.on('end', () => {
                    const b = bundle.split(',');
                    const latest_hash = b[1];
                    if (latest_hash !== hash) {
                        console.log("[download_kr] DATABASE CHANGES FOUND! DOWNLOADING...");
                        diff.KR = [hash, latest_hash];
                        const file = fs.createWriteStream(name_unity3d);
                        http.get(`${cdnAddr}dl/pool/AssetBundles/${latest_hash.substring(0, 2)}/${latest_hash}`, function(response) {
                            const stream = response.pipe(file);
                            stream.on('finish', () => {
                                const { PythonShell } = require('python-shell');
                                PythonShell.run('src/deserialize.py', { args: ["KR", name_unity3d, name] }, function(err) {
                                    if (err) throw err;
                                    console.log(`[download_kr] DOWNLOADED AND CONVERTED DATABASE [${latest_hash}] ; SAVED AS ${name}`);
                                    resolve({success: true, hash: latest_hash});
                                });
                            });
                        });
                    }
                    else {
                        console.log('[download_kr] DATABASE UP TO DATE!');
                        resolve({});
                    }
                });
            }).end();
        }
    });
}

function download_th(version, hash) {
    /*
        priconne-th database notes
        - masterdata is not encrypted, does not need deserialization.
        - the database is served straight up.
    */
    return new Promise(async function (resolve) {
        if (!CHANGED.TH) {
            resolve({});
            return;
        }
        if (!version || hash === undefined) {
            console.log("[download_th] VERSION OR HASH NOT PROVIDED.");
            resolve({});
            return;
        }
        console.log("[download_th] DOWNLOADING DATABASE...");
        const name = `${SETTING.FILE_NAME.TH}.db`;
        let manifest_assetmanifest = "";
        let masterdata_path = "";
        let bundle = "";

        // get masterdata path first (we don't know if it's masterdata, masterdata2, etc)
        https.request({
            host: SETTING.HOST.TH,
            path: `/PCC/Live/dl/Resources/${version}/Tha/AssetBundles/iOS/manifest/manifest_assetmanifest`,
            method: 'GET',
        }, (res) => {
            res.on('data', function(chunk) {
                manifest_assetmanifest += Buffer.from(chunk).toString();
            });
            res.on('end', () => {
                masterdata_path = find_masterdata(manifest_assetmanifest);
                dl();
            });
        }).end();

        // called after masterdata path is found
        function dl() {
            https.request({
                host: SETTING.HOST.TH,
                path: `/PCC/Live/dl/Resources/${version}/Tha/AssetBundles/iOS/${masterdata_path}`,
                method: 'GET',
            }, (res) => {
                res.on('data', function(chunk) {
                    bundle += Buffer.from(chunk).toString();
                });
                res.on('end', () => {
                    const b = bundle.split(',');
                    const latest_hash = b[1];

                    if (latest_hash !== hash) {
                        console.log("[download_th] DATABASE CHANGES FOUND! DOWNLOADING...");
                        diff.TH = [hash, latest_hash];
                        const file = fs.createWriteStream(name);
                        https.get(`https://${SETTING.HOST.TH}/PCC/Live/dl/pool/AssetBundles/${latest_hash.substring(0, 2)}/${latest_hash}`, function(response) {
                            const stream = response.pipe(file);
                            stream.on('finish', () => {
                                // DOWNLOADED DB
                                console.log(`[download_th] DOWNLOADED DATABASE [${latest_hash}] ; SAVED AS ${name}`);
                                resolve({success: true, hash: latest_hash});
                            });
                        });
                    }
                    else {
                        console.log('[download_th] DATABASE UP TO DATE!');
                        resolve({});
                    }
                });
            }).end();
        }
    });
}

function download_tw(version, hash) {
    /*
        priconne-tw database notes
        - masterdata is not encrypted, can use UnityPack to deserialize.
    */
    return new Promise(async function (resolve) {
        if (!CHANGED.TW) {
            resolve({});
            return;
        }
        if (!version || hash === undefined) {
            console.log("[download_tw] VERSION OR HASH NOT PROVIDED.");
            resolve({});
            return;
        }
        console.log("[download_tw] DOWNLOADING DATABASE...");
        const name_unity3d = `${SETTING.FILE_NAME.TW}.unity3d`;
        const name = `${SETTING.FILE_NAME.TW}.db`;
        const version_str = `${version}`.padStart(8, '0');
        let manifest_assetmanifest = "";
        let masterdata_path = "";
        let bundle = "";

        // get masterdata path first (we don't know if it's masterdata, masterdata2, etc)
        https.request({
            host: SETTING.HOST.TW,
            path: `/dl/Resources/${version_str}/Jpn/AssetBundles/iOS/manifest/manifest_assetmanifest`,
            method: 'GET',
        }, (res) => {
            res.on('data', function(chunk) {
                manifest_assetmanifest += Buffer.from(chunk).toString();
            });
            res.on('end', () => {
                masterdata_path = find_masterdata(manifest_assetmanifest);
                dl();
            });
        }).end();

        // called after masterdata path is found
        function dl() {
            https.request({
                host: SETTING.HOST.TW,
                path: `/dl/Resources/${version_str}/Jpn/AssetBundles/iOS/${masterdata_path}`,
                method: 'GET',
            }, (res) => {
                res.on('data', function(chunk) {
                    bundle += Buffer.from(chunk).toString();
                });
                res.on('end', () => {
                    const b = bundle.split(',');
                    const latest_hash = b[1];
                    if (latest_hash !== hash) {
                        console.log("[download_tw] DATABASE CHANGES FOUND! DOWNLOADING...");
                        diff.TW = [hash, latest_hash];
                        const file = fs.createWriteStream(name_unity3d);
                        http.get(`http://${SETTING.HOST.TW}/dl/pool/AssetBundles/${latest_hash.substring(0, 2)}/${latest_hash}`, function(response) {
                            const stream = response.pipe(file);
                            stream.on('finish', () => {
                                const { PythonShell } = require('python-shell');
                                PythonShell.run('src/deserialize.py', { args: ["TW", name_unity3d, name] }, function(err) {
                                    if (err) throw err;
                                    console.log(`[download_tw] DOWNLOADED AND CONVERTED DATABASE [${latest_hash}] ; SAVED AS ${name}`);
                                    resolve({success: true, hash: latest_hash});
                                });
                            });
                        });
                    }
                    else {
                        console.log('[download_tw] DATABASE UP TO DATE!');
                        resolve({});
                    }
                });
            }).end();
        }
    });
}

function find_masterdata(manifest_assetmanifest) {
    const b = manifest_assetmanifest.split('\n');
    const results = b.filter((v) => /masterdata/.test(v));
    return results[0].split(',')[0];
}