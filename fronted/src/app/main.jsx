import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider, theme } from 'antd'
import 'antd/dist/reset.css'
import './app.css'
import { FeatureApp } from './App.jsx'

const appTheme = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: '#63d7ff',
    colorInfo: '#63d7ff',
    colorSuccess: '#69d59c',
    colorWarning: '#f0b35a',
    colorError: '#ff7373',
    colorBgBase: '#101214',
    colorBgContainer: '#171a1d',
    colorBgElevated: '#1c2024',
    colorBorder: '#30363c',
    colorBorderSecondary: '#272c31',
    borderRadius: 6,
    borderRadiusLG: 6,
    fontFamily:
      'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  components: {
    Layout: {
      bodyBg: '#101214',
      headerBg: '#15181b',
      siderBg: '#131619',
    },
    Menu: {
      darkItemBg: '#131619',
      darkItemSelectedBg: '#223139',
      darkItemSelectedColor: '#8ee7ff',
    },
  },
}

export function mountFeatureApp(container) {
  createRoot(container).render(
    <React.StrictMode>
      <ConfigProvider theme={appTheme}>
        <BrowserRouter>
          <FeatureApp />
        </BrowserRouter>
      </ConfigProvider>
    </React.StrictMode>,
  )
}
