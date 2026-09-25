<template>
  <section class="page" data-module="effluent">
    <header class="page-head">
      <div>
        <h2>出水监测管理</h2>
        <p class="page-desc">维护出水记录，围绕监测编号、采样时间、出水流量、化学需氧量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记出水记录</button>
        <button class="btn" type="button" @click="exportRows">导出出水监测清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="report-bar">
      <div class="report-head">
        <strong>达标率报表导出</strong>
        <span class="report-desc">按周期汇总出水流量、化学需氧量、总磷浓度等指标的达标判定，导出该周期超标清单</span>
      </div>
      <label class="filter-item">
        <span>统计周期</span>
        <input v-model="reportPeriod" type="month" />
      </label>
      <button class="btn primary" type="button" :disabled="reportExporting" @click="exportComplianceReport">
        {{ reportExporting ? '正在导出…' : '导出超标清单' }}
      </button>
      <span v-if="reportMessage" class="report-message" :class="{ 'error-text': reportFailed }">{{ reportMessage }}</span>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无出水监测数据，可先登记出水记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条出水监测记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/effluent'
const columns = ["监测编号", "采样时间", "出水流量", "化学需氧量", "氨氮浓度", "总磷浓度", "达标判定", "监测状态"]
const actions = ["开始检测", "判定达标", "标记超标"]
const statuses = ["待检测", "检测中", "已达标", "已超标"]
const stats = [{"label": "今日出水量", "value": 0}, {"label": "达标率", "value": 0}, {"label": "超标次数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 达标率报表导出：周期选择持久化到 localStorage，导出下载后不清空，刷新后保持原样
const REPORT_PERIOD_KEY = 'effluent:compliance:period'
const reportPeriod = ref('')
const reportMessage = ref('')
const reportFailed = ref(false)
const reportExporting = ref(false)

watch(reportPeriod, (value) => {
  if (value) {
    localStorage.setItem(REPORT_PERIOD_KEY, value)
  } else {
    localStorage.removeItem(REPORT_PERIOD_KEY)
  }
})

async function exportComplianceReport() {
  reportMessage.value = ''
  reportFailed.value = false
  if (!reportPeriod.value) {
    reportFailed.value = true
    reportMessage.value = '请先选择统计周期，再导出达标率报表'
    return
  }
  reportExporting.value = true
  try {
    const response = await request(`${ENDPOINT}/compliance/export?period=${encodeURIComponent(reportPeriod.value)}`)
    if (!response.ok) {
      // 无数据周期、重复导出等兜底说明由后端 detail 带回来，原样展示
      let detail = ''
      try {
        const payload = await response.json()
        detail = typeof payload?.detail === 'string' ? payload.detail : ''
      } catch {
        detail = ''
      }
      reportFailed.value = true
      reportMessage.value = detail || `达标率报表导出失败（接口返回 ${response.status}），请稍后重试`
      return
    }
    const blob = await response.blob()
    const disposition = response.headers.get('Content-Disposition') ?? ''
    const matched = disposition.match(/filename\*=UTF-8''([^;]+)/)
    const filename = matched ? decodeURIComponent(matched[1]) : `出水达标率报表_${reportPeriod.value}.csv`
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
    reportMessage.value = `周期 ${reportPeriod.value} 的达标率报表已导出下载，周期选择已保留`
  } catch (error) {
    reportFailed.value = true
    reportMessage.value = error instanceof Error ? `达标率报表导出失败：${error.message}` : '达标率报表导出失败，请稍后重试'
  } finally {
    reportExporting.value = false
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '出水记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('出水监测动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '出水监测操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('出水记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '出水监测列表读取失败'
  }
}

onMounted(() => {
  reportPeriod.value = localStorage.getItem(REPORT_PERIOD_KEY) ?? ''
  void reload()
})
</script>
