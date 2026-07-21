import {
  HourglassOutlined,
  MessageOutlined,
  PlusOutlined,
  StopOutlined,
} from '@ant-design/icons'
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Tabs,
} from 'antd'
import React, { useMemo, useState } from 'react'

import {
  createAgent,
  sendAgentMessage,
  stopAgent,
  waitAgent,
} from './api.js'

const ACTIVE_STATUSES = new Set(['CREATED', 'RUNNING', 'WAITING'])

function agentOptions(instances) {
  return instances.map((item) => ({
    value: item.instanceId,
    label: `${item.role} · ${item.status} · ${item.instanceId.slice(0, 8)}`,
  }))
}

export function AgentGraphControls({ flowId, network, onChanged }) {
  const { message } = App.useApp()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const descriptors = network?.agentDescriptors || []
  const activeInstances = useMemo(
    () => (network?.agentInstances || []).filter((item) => ACTIVE_STATUSES.has(item.status)),
    [network],
  )
  const options = useMemo(() => agentOptions(activeInstances), [activeInstances])

  async function execute(action, successText) {
    setBusy(true)
    try {
      const result = await action()
      message.success(successText(result))
      await onChanged?.()
      return result
    } catch (error) {
      message.error(error.message)
      return null
    } finally {
      setBusy(false)
    }
  }

  const items = [
    {
      key: 'create',
      label: '创建',
      icon: <PlusOutlined />,
      children: (
        <Form
          layout="vertical"
          onFinish={(values) => execute(
            () => createAgent({ flowId, ...values }),
            (result) => `已创建 ${result.role} Agent`,
          )}
        >
          <Form.Item name="role" label="Agent role" rules={[{ required: true }]}>
            <Select
              options={descriptors.filter((item) => item.enabled).map((item) => ({
                value: item.role,
                label: item.displayName,
              }))}
            />
          </Form.Item>
          <Form.Item name="objective" label="任务目标" rules={[{ required: true }]}>
            <Input.TextArea rows={4} maxLength={20000} showCount />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={busy}>
            创建 Agent
          </Button>
        </Form>
      ),
    },
    {
      key: 'message',
      label: '消息',
      icon: <MessageOutlined />,
      children: (
        <Form
          layout="vertical"
          initialValues={{ kind: 'STATUS' }}
          onFinish={(values) => execute(
            () => sendAgentMessage(values),
            () => '消息已投递',
          )}
        >
          <Form.Item name="fromAgentInstanceId" label="发送 Agent" rules={[{ required: true }]}>
            <Select options={options} />
          </Form.Item>
          <Form.Item name="toAgentInstanceId" label="接收 Agent" rules={[{ required: true }]}>
            <Select options={options} />
          </Form.Item>
          <Form.Item name="kind" label="消息类型" rules={[{ required: true }]}>
            <Select options={['REQUEST', 'RESPONSE', 'STATUS', 'REFLECTION', 'ERROR'].map(
              (value) => ({ value, label: value }),
            )} />
          </Form.Item>
          <Form.Item name="summary" label="公开消息" rules={[{ required: true }]}>
            <Input.TextArea rows={4} maxLength={8000} showCount />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<MessageOutlined />} loading={busy}>
            发送消息
          </Button>
        </Form>
      ),
    },
    {
      key: 'wait',
      label: '等待',
      icon: <HourglassOutlined />,
      children: (
        <Form
          layout="vertical"
          initialValues={{ timeoutSeconds: 30 }}
          onFinish={(values) => execute(
            () => waitAgent(values.agentInstanceId, values.timeoutSeconds),
            (result) => `等待结束：${result.status}`,
          )}
        >
          <Form.Item name="agentInstanceId" label="Agent" rules={[{ required: true }]}>
            <Select options={options} />
          </Form.Item>
          <Form.Item name="timeoutSeconds" label="超时（秒）" rules={[{ required: true }]}>
            <InputNumber min={0} max={600} precision={0} />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<HourglassOutlined />} loading={busy}>
            等待状态
          </Button>
        </Form>
      ),
    },
    {
      key: 'stop',
      label: '停止',
      icon: <StopOutlined />,
      children: (
        <Form
          layout="vertical"
          initialValues={{ reason: '操作员请求停止' }}
          onFinish={(values) => execute(
            () => stopAgent(values.agentInstanceId, values.reason),
            () => '停止请求已记录',
          )}
        >
          <Form.Item name="agentInstanceId" label="Agent" rules={[{ required: true }]}>
            <Select options={options} />
          </Form.Item>
          <Form.Item name="reason" label="停止原因" rules={[{ required: true }]}>
            <Input.TextArea rows={3} maxLength={2000} showCount />
          </Form.Item>
          <Button danger htmlType="submit" icon={<StopOutlined />} loading={busy}>
            请求停止
          </Button>
        </Form>
      ),
    },
  ]

  return (
    <>
      <Button
        size="small"
        icon={<MessageOutlined />}
        disabled={!flowId}
        onClick={() => setOpen(true)}
      >
        控制
      </Button>
      <Modal
        title="Agent Graph 控制"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        destroyOnHidden
        width={560}
      >
        <Tabs items={items} />
      </Modal>
    </>
  )
}
