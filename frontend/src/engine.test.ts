import { expect, test, vi } from 'vitest'
import JASSUB from 'jassub'

test('JASSUB module is correctly imported', async () => {
  // 核心目标：确认 JASSUB 被正确导入，且是一个可以被实例化的类/函数
  expect(JASSUB).toBeDefined()
  expect(typeof JASSUB).toBe('function')
})
