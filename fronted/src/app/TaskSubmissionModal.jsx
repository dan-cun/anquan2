import React, { useState } from 'react'
import { InboxOutlined } from '@ant-design/icons'
import { Alert, Form, Input, Modal, Select, Upload } from 'antd'

import { mergeTaskFiles } from './taskSubmission.js'

const { Dragger } = Upload

export function TaskSubmissionModal({ open, progress, onCancel, onSubmit }) {
  const [form] = Form.useForm()
  const [files, setFiles] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  function handleCancel() {
    form.resetFields()
    setFiles([])
    setError('')
    onCancel()
  }

  async function handleFinish(values) {
    if (submitting) return
    setSubmitting(true)
    setError('')
    try {
      await onSubmit({
        objective: values.objective.trim(),
        authorizationScope: values.authorizationScope.trim(),
        constraints: values.constraints?.trim() || '',
        autonomyPolicy: values.autonomyPolicy,
        files: files.map((file) => file.originFileObj || file),
      })
      form.resetFields()
      setFiles([])
    } catch (submitError) {
      setError(submitError.message || '任务提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      className="task-submission-modal"
      title="新建安全任务"
      open={open}
      okText="提交任务"
      cancelText="取消"
      confirmLoading={submitting}
      closable={!submitting}
      mask={{ closable: !submitting }}
      keyboard={!submitting}
      onCancel={submitting ? undefined : handleCancel}
      okButtonProps={{ form: 'task-submission-form', htmlType: 'submit' }}
      width={680}
    >
      <Form
        id="task-submission-form"
        form={form}
        layout="vertical"
        initialValues={{ autonomyPolicy: 'graded' }}
        onFinish={handleFinish}
      >
        <Form.Item
          label="任务目标"
          name="objective"
          rules={[
            { required: true, message: '请输入任务目标' },
            { min: 8, message: '任务目标至少需要 8 个字符' },
          ]}
        >
          <Input.TextArea rows={4} maxLength={10000} showCount />
        </Form.Item>

        <div className="task-form-grid">
          <Form.Item
            label="授权范围"
            name="authorizationScope"
            rules={[
              { required: true, message: '请输入授权范围' },
              { min: 8, message: '授权范围至少需要 8 个字符' },
            ]}
          >
            <Input.TextArea rows={3} maxLength={4000} />
          </Form.Item>
          <div className="task-form-side">
            <Form.Item label="执行策略" name="autonomyPolicy">
              <Select
                options={[
                  { value: 'graded', label: '分级审批' },
                  { value: 'approval_all', label: '全部审批' },
                  { value: 'automatic', label: '自动执行' },
                ]}
              />
            </Form.Item>
            <Form.Item label="约束" name="constraints">
              <Input.TextArea rows={3} maxLength={4000} />
            </Form.Item>
          </div>
        </div>

        <Form.Item label="输入材料" className="task-upload-field">
          <Dragger
            multiple
            fileList={files}
            beforeUpload={() => false}
            onChange={({ fileList }) => setFiles(mergeTaskFiles([], fileList))}
            onRemove={() => true}
          >
            <InboxOutlined />
            <span>添加材料</span>
          </Dragger>
        </Form.Item>

        {progress ? <div className="task-submit-progress">{progress}</div> : null}
        {error ? <Alert type="error" showIcon message={error} /> : null}
      </Form>
    </Modal>
  )
}
