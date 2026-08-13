import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

// VitePress 配置 — EVE 工业助手 中文文档站
// GitHub Pages 站点根路径为 /EVE-Online-Industrial-Assistant/（仓库名），base 必须匹配
export default withMermaid(
  defineConfig({
    lang: 'zh-CN',
    title: 'EVE 工业助手',
    description:
      'EVE Online 工业制造助手 — 多区域价格查询、制造利润计算、物流规划、贸易评分的开源桌面应用',

    base: '/EVE-Online-Industrial-Assistant/',

    head: [
      ['meta', { name: 'theme-color', content: '#61afef' }],
      ['meta', { name: 'og:type', content: 'website' }],
    ],

    themeConfig: {
      siteTitle: 'EVE 工业助手',

      nav: [
        { text: '首页', link: '/' },
        { text: '使用指南', link: '/guide/intro' },
        { text: '用户手册', link: '/user/overview' },
        { text: '开发者', link: '/dev/setup' },
        { text: 'EVE 知识库', link: '/eve_wiki_knowledge_base' },
        { text: '更新日志', link: '/guide/changelog' },
      ],

      sidebar: {
        '/guide/': [
          {
            text: '使用指南',
            items: [
              { text: '项目简介', link: '/guide/intro' },
              { text: '安装与启动', link: '/guide/install' },
              { text: '快速开始', link: '/guide/quickstart' },
              { text: '常见问题', link: '/guide/faq' },
              { text: '更新日志', link: '/guide/changelog' },
            ],
          },
        ],
        '/user/': [
          {
            text: '用户手册',
            items: [
              { text: '界面总览', link: '/user/overview' },
              { text: '工业制造', link: '/user/industry' },
              { text: '物流规划', link: '/user/logistics' },
              { text: 'BOM 管理', link: '/user/bom' },
              { text: '精炼计算', link: '/user/refining' },
              { text: '库存管理', link: '/user/inventory' },
              { text: '价格与评分', link: '/user/pricing' },
            ],
          },
        ],
        '/dev/': [
          {
            text: '开发者',
            items: [
              { text: '开发环境', link: '/dev/setup' },
              { text: '架构说明', link: '/dev/architecture' },
              { text: '数据格式', link: '/dev/data' },
              { text: '数据库 ER 图', link: '/dev/database-er' },
              { text: '测试与规范', link: '/dev/testing' },
              { text: '版本管理', link: '/dev/versioning' },
              { text: '贡献指南', link: '/dev/contribution' },
              { text: 'API 参考', link: '/dev/api-reference' },
              { text: '审计报告与待办', link: '/dev/audit-report' },
              { text: '术语表', link: '/dev/glossary' },
            ],
          },
        ],
      },

      search: { provider: 'local' },

      outline: { level: [2, 3], label: '本页目录' },

      editLink: {
        pattern: 'https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/edit/main/docs/:path',
        text: '在 GitHub 上编辑本页',
      },

      socialLinks: [
        {
          icon: 'github',
          link: 'https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant',
        },
      ],

      docFooter: {
        prev: '上一页',
        next: '下一页',
      },

      lastUpdated: { text: '最后更新', formatOptions: { dateStyle: 'short', timeStyle: 'medium' } },
    },

    // mermaid 图渲染（architecture / ER / 流程 图）
    mermaidPlugin: {
      class: 'mermaid',
    },

    markdown: {
      lineNumbers: true,
    },
  }),
)
