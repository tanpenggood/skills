---
name: vue-build-info
description: 前端项目（Vue2+Webpack / Vue3+Vite）打包构建信息注入。在index.html中注入打包环境与构建时间戳，提供前端读取能力，用于版本追溯。Use when user says "注入版本号"、"注入环境信息"、"构建信息"、"build info"或需要在打包时记录环境和时间信息。
---

# 构建信息注入（Vue2+Webpack / Vue3+Vite）

## 功能

在项目打包构建时，自动向 `index.html` 注入以下信息：
- **构建环境** (buildEnv): development / staging / production
- **构建时间戳** (buildTimestamp): yyyy-MM-dd HH:mm:ss 格式的构建时间

注入方式：通过 `<meta>` 标签嵌入页面，便于前端读取和运维排查。

两种框架的实现入口不同：
- **Vue2 + Webpack**: 通过 `htmlWebpackPlugin.options` 传参 + EJS 模板注入
- **Vue3 + Vite**: 通过 `transformIndexHtml` 插件钩子注入

---

# 一、Vue2 + Webpack（vue.config.js）

## 前置条件

- Vue2 + Webpack 项目（使用 Vue CLI 创建，vue.config.js 配置）
- 项目中存在 `public/index.html` 文件

## 使用步骤

### 1. 修改 vue.config.js

在 `chainWebpack` 函数中添加以下配置：

```javascript
chainWebpack(config) {
    // ... 其他配置

    // 生成 yyyy-MM-dd HH:mm:ss 格式的时间戳
    const now = new Date();
    const buildTimestamp = `${now.getFullYear()}-${(now.getMonth() + 1).toString().padStart(2, '0')}-${now.getDate().toString().padStart(2, '0')} ${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;

    // 向 HtmlWebpackPlugin 传递自定义选项
    config.plugin('html').tap(args => {
        args[0].buildEnv = process.env.VUE_APP_ENV; // 传递构建环境
        args[0].buildTimestamp = buildTimestamp;     // 传递构建时间戳
        return args;
    });

    // ... 其他配置
}
```

### 2. 修改 public/index.html

在 `<head>` 标签内添加以下 meta 标签：

```html
<head>
    <!-- ... 其他内容 -->

    <!-- 构建信息注入 -->
    <meta name="buildEnv" content="<%= htmlWebpackPlugin.options.buildEnv %>">
    <meta name="buildTimestamp" content="<%= htmlWebpackPlugin.options.buildTimestamp %>">
</head>
```

## 完整示例

### vue.config.js 关键配置

```javascript
'use strict';
const path = require('path');

function resolve(dir) {
    return path.join(__dirname, dir);
}

module.exports = {
    publicPath: process.env.VUE_APP_BASE_URL || '/',
    outputDir: 'dist',
    assetsDir: 'static',
    lintOnSave: false,
    productionSourceMap: false,

    chainWebpack(config) {
        config.plugins.delete('preload');
        config.plugins.delete('prefetch');

        // 生成 yyyy-MM-dd HH:mm:ss 格式的时间戳
        const now = new Date();
        const buildTimestamp = `${now.getFullYear()}-${(now.getMonth() + 1).toString().padStart(2, '0')}-${now.getDate().toString().padStart(2, '0')} ${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;

        // 向 HtmlWebpackPlugin 传递自定义选项
        config.plugin('html').tap(args => {
            args[0].buildEnv = process.env.VUE_APP_ENV; // 传递构建环境
            args[0].buildTimestamp = buildTimestamp;     // 传递构建时间戳
            return args;
        });

        // ... 其他配置
    },
};
```

### index.html 关键配置

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
    <meta name="renderer" content="webkit">
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">

    <!-- 构建信息注入 -->
    <meta name="buildEnv" content="<%= htmlWebpackPlugin.options.buildEnv %>">
    <meta name="buildTimestamp" content="<%= htmlWebpackPlugin.options.buildTimestamp %>">

    <link rel="icon" href="<%= BASE_URL %>favicon.ico">
    <title><%= webpackConfig.name %></title>
</head>
<body>
    <div id="app"></div>
</body>
</html>
```

---

# 二、Vue3 + Vite（vite.config.js）

## 前置条件

- Vue3 + Vite 项目（根目录存在 `index.html` 与 `vite.config.js`）
- 使用 `vite build --mode <环境名>` 构建

## 使用步骤

### 1. 修改 vite.config.js

在 `defineConfig` 中通过 mode 拿到构建环境，用 `transformIndexHtml` 钩子注入 meta 标签，同时用 `define` 暴露常量供 JS 内联：

```javascript
import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

function formatTimestamp(date) {
  const pad = (n) => n.toString().padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export default defineConfig(({ mode }) => {
  const buildTimestamp = formatTimestamp(new Date())
  const buildEnv = mode

  return {
    plugins: [
      vue(),
      {
        name: 'inject-build-info',
        transformIndexHtml(html) {
          const metaTags = [
            `<meta name="buildEnv" content="${buildEnv}">`,
            `<meta name="buildTimestamp" content="${buildTimestamp}">`
          ].join('\n    ')
          return html.replace('<head>', `<head>\n    ${metaTags}`)
        }
      }
    ],
    // JS 内联常量（可选，供 setup 中 import.meta 之外的代码使用 __BUILD_ENV__ / __BUILD_TIMESTAMP__）
    define: {
      __BUILD_ENV__: JSON.stringify(buildEnv),
      __BUILD_TIMESTAMP__: JSON.stringify(buildTimestamp)
    },
    base: './',
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      }
    }
  }
})
```

### 2. 构建产物验证

`dist/index.html` 中会生成：

```html
<head>
    <meta name="buildEnv" content="build">
    <meta name="buildTimestamp" content="2026-09-15 18:48:44">
    ...
</head>
```

### 3. 环境变量（可选）

`.env` 文件中自定义环境标识（`VITE_APP_` 前缀），可在代码中通过 `import.meta.env.VITE_APP_ENV` 读取。注意：`transformIndexHtml` 里的 `buildEnv` 默认取 Vite 的 `mode`（即 `--mode` 参数），如需用自定义变量可改为 `loadEnv`：

```javascript
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const buildEnv = env.VITE_APP_ENV || mode
  // 其余同上
})
```

---

# 三、前端读取构建信息（两种方案通用）

注入到 `<head>` 的 meta 标签是纯静态的，与框架无关，前端读取方式完全一致。创建 `utils/buildInfo.js`：

```javascript
export function getBuildInfo() {
    return {
        env: document.querySelector('meta[name="buildEnv"]')?.content || 'unknown',
        timestamp: document.querySelector('meta[name="buildTimestamp"]')?.content || 'unknown'
    };
}
```

在 Vue 组件中调用：

```javascript
import { getBuildInfo } from '@/utils/buildInfo'

const { env, timestamp } = getBuildInfo()
```

`getBuildInfo()` 为可选能力：即使不读取，`buildEnv` / `buildTimestamp` 的 meta 标签已写入 `index.html`，即可通过浏览器开发者工具查看用于运维排查。

---

# 通用说明

## 环境变量说明

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| VUE_APP_ENV (Vue2) / VITE_APP_ENV (Vue3) | 构建环境 | development / staging / production |
| buildEnv | 注入到页面的环境标识 | development / staging / production |
| buildTimestamp | 注入到页面的构建时间 | 2025-11-18 15:05:23 |

## 常见问题

### Q: 为什么不用 filenameHashing / asset hash 添加版本号？

A: 本方案使用时间戳作为版本标识，更直观且便于追溯。如需禁用 hash，可设置：
- Vue2：`filenameHashing: false, // 打包时不使用hash值`
- Vue3：`build.rollupOptions.output.assetFileNames = 'assets/[name].[ext]'`

### Q: 如何在不同环境使用不同配置？

A: 通过 `.env` 文件设置环境变量：
```bash
# Vue2: .env.development / .env.production
VUE_APP_ENV=development

# Vue3: .env.dev / .env.build
VITE_APP_ENV=dev
```

### Q: Vue3 下 buildEnv 显示为 "development" / "production" 而非 env 文件中定义的值？

A: `transformIndexHtml` 里的 `buildEnv` 默认取 Vite 的 `mode`（--mode 参数）。如需自定义标识，用 `loadEnv` 读取 `.env` 中的变量，见上文 Vue3 步骤 3。

## 参考

- [Vue CLI 配置参考](https://cli.vuejs.org/zh/config/)
- [Webpack HtmlWebpackPlugin](https://github.com/jantimon/html-webpack-plugin)
- [Vite 配置参考（defineConfig / transformIndexHtml / environment variables）](https://vite.dev/config/)
- [Vite env variables and modes](https://vite.dev/guide/env-and-mode.html)
