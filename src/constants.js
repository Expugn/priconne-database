const SETTING = Object.freeze({
    DEFAULT_TRUTH_VERSION: Object.freeze({
        CN: -1, // unused
        EN: 10000000,
        JP: 10010800,
        KR: 10000000,
        TH: 10026400,
        TW: 0,
    }),
    HOST: Object.freeze({
        CN: '', // unused
        EN: 'assets-priconne-redive-us.akamaized.net',
        JP: 'prd-priconne-redive.akamaized.net',
        KR: 'patch.pcr.kakaogame.com', // unused
        TH: 'patch.i3play.com',
        TW: 'img-pc.so-net.tw',
    }),
    FILE_NAME: Object.freeze({
        CN: 'master_cn',
        EN: 'master_en',
        JP: 'master_jp',
        KR: 'master_kr',
        TH: 'master_th',
        TW: 'master_tw',
    }),
    TEST_MAX: Object.freeze({
        CN: 0, // unused
        EN: 20,
        JP: 20,
        KR: 1000, // check up to 10,000 truth versions
        TH: 200,
        TW: 0, // unused
    }),
    TEST_MULTIPLIER: 10,
});

function request_http(host, path, download = false) {
    return new Promise((resolve) => {
        const http = require('http');
        http.request({
            host,
            path,
            method: 'GET',
        }, (res) => {
            if (!download) {
                resolve(res);
                return;
            }
            let bundle = "";
            res.on('data', (chunk) => {
                bundle += Buffer.from(chunk).toString();
            });
            res.on('end', () => {
                resolve({res, bundle});
            });
        }).end();
    });
}

function request_https(host, path, download = false) {
    return new Promise((resolve) => {
        const https = require('https');
        https.request({
            host,
            path,
            method: 'GET',
        }, (res) => {
            if (!download) {
                resolve(res);
                return;
            }
            let bundle = "";
            res.on('data', (chunk) => {
                bundle += Buffer.from(chunk).toString();
            });
            res.on('end', () => {
                resolve({res, bundle});
            });
        }).end();
    });
}

function cn_get_maintenance_status() {
    return new Promise((resolve) => {
        const https = require('https');
        https.request({
            host: "le1-prod-all-gs-gzlj.bilibiligame.net",
            path: "/source_ini/get_maintenance_status?format=json",
            method: 'POST',
            headers: {
                "RES-KEY": "ab00a0a6dd915a052a2ef7fd649083e5"
            },
        }, (res) => {
            let bundle = "";
            res.on('data', (chunk) => {
                bundle += Buffer.from(chunk).toString();
            });
            res.on('end', () => {
                resolve(JSON.parse(bundle));
            });
        }).end();
    });
}

module.exports = {
    SETTING,
    request_http,
    request_https,
    cn_get_maintenance_status
};