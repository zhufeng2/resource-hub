'use strict';

class AccountApi {
  constructor(transport) {
    this.transport = transport;
  }

  getSpace() {
    return this.transport.call('account.space', {
      params: { fetch_subscribe: true, _ch: 'home', fetch_identity: true },
    });
  }
}

module.exports = { AccountApi };
