export const MODEL_PROVIDER_PRESETS = [
  {
    value: 'qwen',
    label: 'Qwen / DashScope',
    model: 'qwen-plus',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },
  {
    value: 'deepseek',
    label: 'DeepSeek',
    model: 'deepseek-chat',
    baseUrl: 'https://api.deepseek.com',
  },
  {
    value: 'openai',
    label: 'OpenAI',
    model: 'gpt-4.1-mini',
    baseUrl: 'https://api.openai.com/v1',
  },
  {
    value: 'moonshot',
    label: 'Moonshot / Kimi',
    model: 'moonshot-v1-8k',
    baseUrl: 'https://api.moonshot.cn/v1',
  },
  {
    value: 'zhipu',
    label: 'Zhipu GLM',
    model: 'glm-4-flash',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
  },
  {
    value: 'siliconflow',
    label: 'SiliconFlow',
    model: 'deepseek-ai/DeepSeek-V3',
    baseUrl: 'https://api.siliconflow.cn/v1',
  },
  {
    value: 'openai-compatible',
    label: 'Custom OpenAI Compatible',
    model: '',
    baseUrl: '',
  },
]

export function getModelProviderPreset(provider) {
  return MODEL_PROVIDER_PRESETS.find((item) => item.value === provider) || null
}

export function modelProviderOptions() {
  return MODEL_PROVIDER_PRESETS.map(({ value, label }) => ({ value, label }))
}
