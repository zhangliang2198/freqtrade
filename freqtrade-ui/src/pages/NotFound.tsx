/**
 * 404 page — monochrome, one way out.
 */

import { Link } from 'react-router-dom'
import { Button } from '@douyinfe/semi-ui'
import { IconHome, IconSearch } from '@douyinfe/semi-icons'

import { Panel } from '../components/primitives'

export function NotFound() {
  return (
    <div className="ft-page">
      <Panel title="404" icon={<IconSearch />} sub="页面不存在">
        <div
          className="ft-col"
          style={{ gap: 'var(--ft-gap-5)', alignItems: 'center', padding: 'var(--ft-gap-7) 0' }}
        >
          <div
            className="ft-num"
            style={{
              fontSize: 'var(--ft-font-2xl)',
              fontWeight: 700,
              letterSpacing: '-0.04em',
              color: 'var(--ft-ink-0)',
            }}
          >
            404
          </div>
          <div style={{ fontSize: 'var(--ft-font-lg)', color: 'var(--ft-ink-1)' }}>
            找不到该页面
          </div>
          <div
            className="ft-faint"
            style={{ fontSize: 'var(--ft-font-sm)', textAlign: 'center', maxWidth: 420 }}
          >
            你访问的地址不存在，或者对应的功能尚未启用。
          </div>
          <Link to="/dashboard" style={{ textDecoration: 'none' }}>
            <Button size="small" icon={<IconHome />}>
              返回总览
            </Button>
          </Link>
        </div>
      </Panel>
    </div>
  )
}
