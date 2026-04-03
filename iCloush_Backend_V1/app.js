// ============================================
// iCloush 智慧工厂 — 全局 App
// ============================================

// ═══════════════════════════════════════════════════
// 【环境配置区】— 联调时只需改这里
// ═══════════════════════════════════════════════════
// 模式一：纯前端开发（Mock 数据，无需后端）
//   useMock = true，BASE_URL 不生效
//
// 模式二：本地联调（Docker 后端 + 微信开发者工具）
//   useMock = false
//   BASE_URL = 'http://你的电脑IP:8000'  （ipconfig 查看 IPv4）
//   WS_URL   = 'ws://你的电脑IP:8000/ws/iot'
//   微信开发者工具 → 详情 → 本地设置 → 勾选"不校验合法域名"
//
// 模式三：生产环境（微信云托管）
//   useMock = false
//   BASE_URL = 'https://api.icloush.com'
//   WS_URL   = 'wss://api.icloush.com/ws/iot'
// ═══════════════════════════════════════════════════

var USE_MOCK = false;  // 【开关】true=Mock模式, false=真实后端

// 本地联调时，将下面的 IP 替换为你电脑的局域网 IPv4 地址
// Windows: cmd → ipconfig → 无线局域网适配器 WLAN → IPv4 地址
// Mac: ifconfig → en0 → inet
var LOCAL_IP = '192.168.1.4';  // ← 替换为你的 IP

// 根据模式自动选择地址
var BASE_URL = USE_MOCK ? '' : ('http://' + LOCAL_IP + ':8000');
var WS_URL = USE_MOCK ? '' : ('ws://' + LOCAL_IP + ':8000/ws/iot');

// 生产环境地址（部署时取消注释，注释掉上面两行）
// var BASE_URL = 'https://api.icloush.com';
// var WS_URL = 'wss://api.icloush.com/ws/iot';

// Mock 数据模块（解耦：仅在 useMock=true 时使用）
var mockData = require('./utils/mockData');

App({
  globalData: {
    userInfo: null,
    token: null,
    baseUrl: BASE_URL,
    wsConnected: false,
    wsSocket: null,
    wsReconnectTimer: null,
    wsHeartbeatTimer: null,
    wsReconnectDelay: 1000, // 初始重连延迟1秒，指数退避最大30秒
    // Mock开关（开发阶段开启，后端就绪后改为 false）
    useMock: USE_MOCK,
    // 排班数据全局共享（总览页 ↔ 排班页 同步）
    scheduleData: null,
    // 账户角色（admin / staff）
    accountRole: null,
  },

  onLaunch: function () {
    console.log('[iCloush] 启动模式:', USE_MOCK ? 'Mock 数据' : '真实后端 → ' + BASE_URL);
    this.checkLogin();
  },

  // 守则九补丁：从后台切回时检查并恢复 WebSocket 连接
  onShow: function () {
    if (
      this.globalData.token &&
      !this.globalData.wsConnected &&
      !this.globalData.useMock &&
      !this.globalData.wsReconnectTimer
    ) {
      console.log('[应用] 从后台切回，检查并重连 WebSocket');
      this.connectWebSocket();
    }
  },

  // ============================================
  // 登录与鉴权
  // ============================================
  checkLogin: function () {
    var token = wx.getStorageSync('token');
    var userInfo = wx.getStorageSync('userInfo');

    // 守则：切换模式后自动清除旧 token
    // Mock token 不能发给真实后端，真实 token 不能用于 Mock 模式
    if (token && userInfo) {
      var isMockToken = (typeof token === 'string') && (token.indexOf('mock_') === 0 || token.indexOf('token_') === 0);
      if (!this.globalData.useMock && isMockToken) {
        // 当前是真实后端模式，但存的是 Mock token → 清除
        console.log('[iCloush] 检测到 Mock token，当前为真实后端模式，清除旧登录状态');
        wx.removeStorageSync('token');
        wx.removeStorageSync('userInfo');
        wx.removeStorageSync('accountRole');
        return;
      }
      if (this.globalData.useMock && !isMockToken) {
        // 当前是 Mock 模式，但存的是真实 token → 清除
        console.log('[iCloush] 检测到真实 token，当前为 Mock 模式，清除旧登录状态');
        wx.removeStorageSync('token');
        wx.removeStorageSync('userInfo');
        wx.removeStorageSync('accountRole');
        return;
      }

      this.globalData.token = token;
      this.globalData.userInfo = userInfo;
      this.globalData.accountRole = wx.getStorageSync('accountRole') || 'staff';
      if (!this.globalData.useMock) {
        this.connectWebSocket();
      }
    }
    // 未登录状态不再自动Mock登录，等待用户通过login页面白名单验证
  },

  login: function (code, callback) {
    if (this.globalData.useMock) {
      // 调试模式：Mock 登录（管理员账号）
      var mockUser = {
        id: 'u001',
        name: '张伟',
        avatar_key: 'male_admin_01',
        role: 7,
        department: '洗涤工厂',
        skills: ['洗涤龙', '单机洗', '烫平机', '物流驾驶'],
        skill_tags: ['洗涤龙', '单机洗', '烫平机', '物流驾驶'],
        is_multi_post: true,
        total_points: 3860,
        monthly_points: 420,
        points_balance: 3860,
        task_completed: 187,
        status: 'active',
      };
      this.globalData.userInfo = mockUser;
      this.globalData.token = 'mock_token_admin';
      wx.setStorageSync('token', 'mock_token_admin');
      wx.setStorageSync('userInfo', mockUser);
      if (callback) callback(null, mockUser);
      return;
    }
    var self = this;
    wx.request({
      url: BASE_URL + '/api/v1/auth/wechat-login',
      method: 'POST',
      data: { code: code },
      success: function (res) {
        if (res.data.code === 200) {
          var token = res.data.token;
          var user = res.data;
          self.globalData.token = token;
          self.globalData.userInfo = {
            id: user.user_id,
            name: user.name,
            role: user.role,
          };
          wx.setStorageSync('token', token);
          wx.setStorageSync('userInfo', self.globalData.userInfo);
          self.connectWebSocket();
          if (callback) callback(null, self.globalData.userInfo);
        } else {
          if (callback) callback(res.data.detail || '登录失败');
        }
      },
      fail: function (err) {
        if (callback) callback(err);
      },
    });
  },

  // 账号密码登录（本地联调用）
  loginWithPassword: function (username, password, callback) {
    if (this.globalData.useMock) {
      // Mock 模式走原有逻辑
      this.login(null, callback);
      return;
    }
    var self = this;
    wx.request({
      url: BASE_URL + '/api/v1/auth/verify',
      method: 'POST',
      data: { username: username, password: password },
      header: { 'Content-Type': 'application/json' },
      success: function (res) {
        if (res.data.token) {
          var token = res.data.token;
          self.globalData.token = token;
          self.globalData.userInfo = {
            id: res.data.user_id,
            name: res.data.name,
            role: res.data.role,
          };
          wx.setStorageSync('token', token);
          wx.setStorageSync('userInfo', self.globalData.userInfo);
          // 根据角色设置 accountRole
          self.globalData.accountRole = res.data.role >= 5 ? 'admin' : 'staff';
          wx.setStorageSync('accountRole', self.globalData.accountRole);
          self.connectWebSocket();
          if (callback) callback(null, self.globalData.userInfo);
        } else {
          if (callback) callback(res.data.detail || '账号或密码错误');
        }
      },
      fail: function (err) {
        wx.showToast({ title: '网络错误', icon: 'none' });
        if (callback) callback(err);
      },
    });
  },

  logout: function () {
    this.globalData.token = null;
    this.globalData.userInfo = null;
    this.globalData.accountRole = null;
    wx.removeStorageSync('token');
    wx.removeStorageSync('userInfo');
    wx.removeStorageSync('accountRole');
    this.disconnectWebSocket();
    wx.reLaunch({ url: '/pages/login/index' });
  },

  // ============================================
  // WebSocket 心跳重连（守则九）
  // ============================================
  /**
   * 【Phase 3B/3C 修复】WebSocket user_id=0 问题
   *
   * 根因分析：
   *   原代码: wsUrlWithParams = WS_URL + '?user_id=' + (userInfo.id || 0)
   *   后端:   user_id = websocket.query_params.get("user_id", "0")
   *
   *   问题1: 真实模式下 loginWithPassword 存的是 userInfo.id = res.data.user_id (整数)
   *          但 wechat-login 存的是 userInfo.id = user.user_id
   *          如果后端返回字段名不一致，id 可能为 undefined → 拼接后变成 "user_id=undefined"
   *          后端 int("undefined") 失败 → 降级为 0 → 被拒绝
   *
   *   问题2: Mock 模式下 id='u001'（字符串），后端 int("u001") 也失败
   *
   * 修复方案：
   *   前端: 不再通过 query_params 传 user_id，改为通过 Authorization header 传 JWT Token
   *         后端从 Token 中解析 user_id 和 role（可靠且安全）
   *   后端: 优先从 Authorization header 解析 JWT，降级才读 query_params
   */
  connectWebSocket: function () {
    if (this.globalData.useMock) return;
    if (this.globalData.wsConnected) return;

    var self = this;
    var token = this.globalData.token || '';

    // 【修复】不再拼接 user_id/role 到 URL，改为通过 header 传 JWT Token
    // 后端会从 Authorization header 中解析出 user_id 和 role
    // 同时保留 query_params 作为降级（从 token 解析 user_id 写入 URL）
    var userInfo = this.globalData.userInfo || {};
    var userId = userInfo.id || 0;
    var userRole = userInfo.role || 1;
    var wsUrlWithParams = WS_URL + '?user_id=' + userId + '&role=' + userRole;

    console.log('[WebSocket] 正在连接:', wsUrlWithParams, '| user_id:', userId);

    // 校验：如果没有 token 且 user_id 无效，不发起连接
    if (!token && (!userId || userId <= 0)) {
      console.warn('[WebSocket] 无有效凭证，跳过连接');
      return;
    }

    var socket = wx.connectSocket({
      url: wsUrlWithParams,
      header: {
        'Authorization': 'Bearer ' + token,
      },
    });

    self.globalData.wsSocket = socket;

    socket.onOpen(function () {
      console.log('[WebSocket] 连接成功, user_id:', userId);
      self.globalData.wsConnected = true;
      self.globalData.wsReconnectDelay = 1000;
      self.startHeartbeat();
    });

    socket.onMessage(function (res) {
      try {
        var msg = JSON.parse(res.data);
        if (msg.type === 'pong' || res.data === 'pong') return;
        self.broadcastWsMessage(msg);
      } catch (e) {}
    });

    socket.onClose(function (res) {
      console.log('[WebSocket] 连接断开, code:', res.code, 'reason:', res.reason);
      self.globalData.wsConnected = false;
      self.stopHeartbeat();
      // 如果是被服务端主动拒绝（4001=无效user_id），不重连
      if (res.code === 4001) {
        console.warn('[WebSocket] 服务端拒绝连接:', res.reason, '| 不再重连');
        return;
      }
      self.scheduleReconnect();
    });

    socket.onError(function (err) {
      console.log('[WebSocket] 连接错误:', JSON.stringify(err));
      self.globalData.wsConnected = false;
      self.stopHeartbeat();
      self.scheduleReconnect();
    });
  },

  startHeartbeat: function () {
    this.stopHeartbeat();
    var self = this;
    this.globalData.wsHeartbeatTimer = setInterval(function () {
      if (self.globalData.wsConnected && self.globalData.wsSocket) {
        self.globalData.wsSocket.send({ data: 'ping' });
      }
    }, 30000);
  },

  stopHeartbeat: function () {
    if (this.globalData.wsHeartbeatTimer) {
      clearInterval(this.globalData.wsHeartbeatTimer);
      this.globalData.wsHeartbeatTimer = null;
    }
  },

  scheduleReconnect: function () {
    if (this.globalData.wsReconnectTimer) return;
    var delay = Math.min(this.globalData.wsReconnectDelay, 30000);
    var self = this;
    console.log('[WebSocket] ' + delay + '毫秒后重连...');
    this.globalData.wsReconnectTimer = setTimeout(function () {
      self.globalData.wsReconnectTimer = null;
      self.globalData.wsReconnectDelay = Math.min(delay * 2, 30000);
      self.connectWebSocket();
    }, delay);
  },

  disconnectWebSocket: function () {
    this.stopHeartbeat();
    if (this.globalData.wsReconnectTimer) {
      clearTimeout(this.globalData.wsReconnectTimer);
      this.globalData.wsReconnectTimer = null;
    }
    if (this.globalData.wsSocket) {
      this.globalData.wsSocket.close();
      this.globalData.wsSocket = null;
    }
    this.globalData.wsConnected = false;
  },

  // WebSocket 消息广播（发布-订阅模式）
  _wsListeners: {},
  subscribeWs: function (key, callback) {
    this._wsListeners[key] = callback;
  },
  unsubscribeWs: function (key) {
    delete this._wsListeners[key];
  },
  broadcastWsMessage: function (msg) {
    var listeners = this._wsListeners;
    var keys = Object.keys(listeners);
    for (var i = 0; i < keys.length; i++) {
      try { listeners[keys[i]](msg); } catch (e) {}
    }
  },

  // ============================================
  // 统一 HTTP 请求（含 Mock 拦截，支持回调和 Promise 双模式）
  // ============================================
  request: function (options) {
    var url = options.url;
    var method = options.method || 'GET';
    var data = options.data;
    var success = options.success;
    var fail = options.fail;
    var self = this;

    // ── Mock 模式 ──────────────────────────────────────────
    if (this.globalData.useMock) {
      var mockRes = mockData.getMockResponse(url, method, data);
      if (success) {
        // 回调风格
        setTimeout(function () { success(mockRes); }, 30 + Math.random() * 50);
        return undefined;
      }
      // Promise 风格
      return new Promise(function (resolve) {
        setTimeout(function () { resolve(mockRes); }, 30 + Math.random() * 50);
      });
    }

    // ── 真实请求 ───────────────────────────────────────────
    if (success) {
      // 回调风格
      wx.request({
        url: BASE_URL + url,
        method: method,
        data: data,
        header: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer ' + (self.globalData.token || ''),
        },
        success: function (res) {
          if (res.data && res.data.code === 401) { self.logout(); return; }
          success(res.data);
        },
        fail: function (err) {
          wx.showToast({ title: '网络错误，请重试', icon: 'none' });
          if (fail) fail(err);
        },
      });
      return undefined;
    }

    // Promise 风格
    return new Promise(function (resolve, reject) {
      wx.request({
        url: BASE_URL + url,
        method: method,
        data: data,
        header: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer ' + (self.globalData.token || ''),
        },
        success: function (res) {
          if (res.data && res.data.code === 401) { self.logout(); return; }
          resolve(res.data);
        },
        fail: function (err) {
          wx.showToast({ title: '网络错误，请重试', icon: 'none' });
          reject(err);
        },
      });
    });
  },
});
