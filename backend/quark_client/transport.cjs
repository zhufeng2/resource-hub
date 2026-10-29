'use strict';

const https = require('node:https');
const { ENDPOINTS, PC, SHARE } = require('./endpoints.cjs');
const { readCookie, updateCookies } = require('./auth.cjs');

class ApiError extends Error {
  constructor(message, { endpoint, httpStatus, businessCode, outcomeUnknown = false } = {}) {
    super(message);
    this.name = 'ApiError';
    this.endpoint = endpoint;
    this.httpStatus = httpStatus;
    this.businessCode = businessCode;
    this.outcomeUnknown = outcomeUnknown;
    // 不附带 URL、请求头、响应正文或原始错误对象。
  }
}

class Transport {
  constructor({
    cookieFile,
    cookies,
    allowWrites = false,
    timeoutMs = 20000,
    requestImpl = https.request,
    onResponse,
  } = {}) {
    const seed = cookies || (cookieFile ? readCookie(cookieFile) : new Map());
    this.cookies = new Map([
      [PC, seed],
      [SHARE, new Map(seed)],
    ]);
    this.allowWrites = allowWrites === true;
    this.timeoutMs = timeoutMs;
    this.requestImpl = requestImpl;
    this.onResponse = onResponse;
  }

  /** 只能调用注册表内的接口；不接受任意主机，不跟随重定向，不自动重试。 */
  async call(name, { params = {}, body, authenticated } = {}) {
    const endpoint = ENDPOINTS[name];
    if (!endpoint) throw new ApiError('未知接口名称');
    if (endpoint.write && !this.allowWrites)
      throw new ApiError('写入未启用：需要 allowWrites:true', { endpoint: name });

    const useCookie = authenticated ?? !endpoint.anonymous;
    const jar = this.cookies.get(endpoint.origin);
    if (!endpoint.anonymous && !useCookie)
      throw new ApiError('此接口需要账号会话', { endpoint: name });
    if (useCookie && !jar.size) throw new ApiError('此接口需要本地 Cookie', { endpoint: name });
    if (endpoint.method === 'GET' && body !== undefined)
      throw new ApiError('GET 接口不能携带 JSON 请求体');

    const url = new URL(endpoint.path, endpoint.origin);
    const query = { pr: 'ucpro', fr: 'pc', uc_param_str: '', ...params };
    url.search = new URLSearchParams(
      Object.entries(query).filter(([, value]) => value !== undefined)
    ).toString();
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const headers = {
      Origin: 'https://pan.quark.cn',
      Referer: 'https://pan.quark.cn/',
      'User-Agent': 'Mozilla/5.0',
      Accept: 'application/json',
      'Accept-Encoding': 'identity',
    };
    if (useCookie) headers.Cookie = [...jar].map(([key, value]) => key + '=' + value).join('; ');
    if (payload !== undefined) {
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = Buffer.byteLength(payload);
    }

    return new Promise((resolve, reject) => {
      let settled = false;
      let sent = false;
      let timer;
      const finish = (error, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        error ? reject(error) : resolve(value);
      };
      const fail = (message) =>
        finish(
          new ApiError(message, {
            endpoint: name,
            outcomeUnknown: endpoint.write && sent,
          })
        );

      let req;
      try {
        req = this.requestImpl(url, { method: endpoint.method, headers }, (res) => {
          let size = 0;
          const chunks = [];
          res.on('data', (chunk) => {
            size += chunk.length;
            if (size > 8 * 1024 * 1024) {
              fail('响应超过 8 MiB，已停止读取');
              res.destroy();
            } else chunks.push(chunk);
          });
          res.on('error', () => fail('响应读取中断；写入时需核对实际结果'));
          res.on('aborted', () => fail('响应中断；写入时需核对实际结果'));
          res.on('end', () => {
            if (settled) return;
            const httpStatus = res.statusCode;
            if (httpStatus !== 200) {
              return finish(
                new ApiError('接口 HTTP ' + httpStatus + '；未跟随跳转', {
                  endpoint: name,
                  httpStatus,
                  outcomeUnknown: endpoint.write && httpStatus >= 500,
                })
              );
            }
            let result;
            try {
              result = JSON.parse(Buffer.concat(chunks).toString('utf8'));
            } catch {
              return fail('响应不是有效 JSON；未输出原始正文');
            }

            const code = result?.code;
            this.onResponse?.({
              endpoint: name,
              httpStatus,
              businessCode: typeof code === 'number' ? code : undefined,
            });
            if (code !== 0) {
              return finish(
                new ApiError('接口业务状态不是成功 code=0', {
                  endpoint: name,
                  httpStatus,
                  businessCode: typeof code === 'number' ? code : undefined,
                })
              );
            }
            if (useCookie) updateCookies(jar, res.headers['set-cookie']);
            finish(null, result);
          });
        });
        req.on('error', () => fail('连接未完成；写入时先核对结果，不自动重试'));
        timer = setTimeout(() => {
          fail('请求超时；写入结果可能不确定，不自动重试');
          req.destroy();
        }, this.timeoutMs);
        sent = true;
        req.end(payload);
      } catch {
        fail('请求创建失败；未输出原始错误');
      }
    });
  }
}

module.exports = { Transport, ApiError };
