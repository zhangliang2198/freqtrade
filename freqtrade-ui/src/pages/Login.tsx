/**
 * Login / bot connection screen.
 *
 * Each successful login registers a bot connection; several can coexist and be
 * switched from the topbar.
 */

import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Banner, Button, Form, Typography } from '@douyinfe/semi-ui'
import { IconLink, IconLock, IconUser } from '@douyinfe/semi-icons'

import { useBots } from '../state/bots'
import { useTheme } from '../state/theme'
import { Tag } from '../components/primitives'

const DEFAULT_URL = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8081'

interface LoginValues {
  botName?: string
  baseUrl: string
  username: string
  password: string
}

export function Login() {
  const { bots, connect } = useBots()
  const { mode, toggle } = useTheme()
  const navigate = useNavigate()
  const location = useLocation()

  const [error, setError] = useState<string | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const formApi = useRef<{ reset: () => void } | null>(null)

  const from = (location.state as { from?: string } | null)?.from

  // Already connected — skip straight through.
  useEffect(() => {
    if (bots.length > 0) {
      navigate(from && from !== '/login' ? from : '/dashboard', { replace: true })
    }
  }, [bots.length, navigate, from])

  // Semi's `<Form>` owns the field state, so values arrive here instead of from
  // controlled inputs (Form.Input rejects `value`/`onChange`).
  const submit = async (values: LoginValues) => {
    setBusy(true)
    setError(undefined)
    try {
      await connect({
        name: values.botName?.trim() ?? '',
        baseUrl: values.baseUrl.trim(),
        username: values.username,
        password: values.password,
      })
      navigate(from && from !== '/login' ? from : '/dashboard', { replace: true })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      if (/401|incorrect|unauthor/i.test(message)) {
        setError('已连上机器人，但认证失败：用户名或密码不正确。')
      } else {
        setError(
          `无法连接 ${values.baseUrl}。请确认机器人正在运行、REST API 已启用，并且该地址可访问。\n` +
            `可在浏览器打开 ${values.baseUrl}/api/v1/ping 验证。若地址与当前页面不同源，` +
            `还需把本页面地址加入 freqtrade 配置的 api_server.CORS_origins，` +
            `或在开发时用 VITE_USE_PROXY=true 走同源代理。`,
        )
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="ft-login">
      <div className="ft-login-card">
        <div className="ft-login-brand">
          <span className="ft-brand-mark">FT</span>
          <span className="ft-login-title">Freqtrade Console</span>
          <span style={{ marginLeft: 'auto' }}>
            <Button size="small" theme="borderless" type="tertiary" onClick={toggle}>
              {mode === 'dark' ? '浅色' : '深色'}
            </Button>
          </span>
        </div>
        <div className="ft-login-hint">
          连接 freqtrade REST API（<span className="ft-mono-sm">api_server</span>
          ）。凭据仅保存在本地浏览器。
        </div>

        {error && (
          <Banner
            type="danger"
            description={<span style={{ whiteSpace: 'pre-wrap' }}>{error}</span>}
            closeIcon={null}
            style={{ marginBottom: 'var(--ft-gap-5)' }}
          />
        )}

        <Form
          labelPosition="top"
          initValues={{ botName: '', baseUrl: DEFAULT_URL, username: '', password: '' }}
          onSubmit={submit}
          getFormApi={(api) => {
            formApi.current = api as unknown as { reset: () => void }
          }}
          style={{ width: '100%' }}
        >
          <Form.Input
            field="botName"
            label="名称"
            placeholder="例如 main / dry-run"
            autoComplete="off"
          />
          <Form.Input
            field="baseUrl"
            label="API 地址"
            prefix={<IconLink />}
            placeholder="http://127.0.0.1:8081"
            autoComplete="off"
            rules={[{ required: true, message: 'API 地址必填' }]}
          />
          <Form.Input
            field="username"
            label="用户名"
            prefix={<IconUser />}
            placeholder="freqtrader"
            autoComplete="username"
            rules={[{ required: true, message: '用户名必填' }]}
          />
          <Form.Input
            field="password"
            label="密码"
            mode="password"
            prefix={<IconLock />}
            autoComplete="current-password"
            rules={[{ required: true, message: '密码必填' }]}
          />
          <div
            className="ft-row"
            style={{ marginTop: 'var(--ft-gap-5)', gap: 'var(--ft-gap-4)' }}
          >
            <Button
              htmlType="submit"
              theme="solid"
              type="primary"
              loading={busy}
              style={{ flex: '1 1 auto' }}
            >
              连接
            </Button>
            <Button
              theme="borderless"
              type="tertiary"
              disabled={busy}
              onClick={() => {
                formApi.current?.reset()
                setError(undefined)
              }}
            >
              重置
            </Button>
          </div>
        </Form>

        {bots.length > 0 && (
          <div style={{ marginTop: 'var(--ft-gap-5)' }}>
            <Typography.Text type="tertiary" size="small">
              已保存的连接
            </Typography.Text>
            <div className="ft-row wrap" style={{ marginTop: 'var(--ft-gap-3)' }}>
              {bots.map((bot) => (
                <Tag key={bot.id} variant="plain" title={bot.baseUrl}>
                  {bot.name}
                </Tag>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
