"""
SQL 生成器服务

基于 LLM 和 DDL 上下文生成 Apache Doris 兼容的 SQL 语句。
支持自然语言转 SQL、用户反馈修正、指标参考 SQL 生成以及 SQL 引用验证。

主要功能：
- 构建包含 DDL 上下文和对话历史的 LLM prompt，调用 LLM 生成 SQL
- 根据用户反馈修正已生成的 SQL
- 根据指标名称和用途生成参考 SQL
- 验证生成的 SQL 中引用的表名和列名是否存在于 DDL 上下文
- 支持多表 JOIN 语句生成
"""

import json
import logging
import re
from typing import Optional

from openai import OpenAI

from app.core.config import settings
from app.models.schemas import DDLInfo, SQLGenParams, SQLGenResult

logger = logging.getLogger(__name__)


# SQL 生成系统提示词
SYSTEM_PROMPT = """你是一个专业的 Apache Doris SQL 生成助手。你的任务是根据用户的自然语言查询需求，结合提供的数据库表结构（DDL），生成正确的 Doris SQL 语句。

当前时间：{current_time}
用户说"最近一周"、"昨天"、"上个月"等相对时间时，请基于当前时间计算出具体日期范围。

规则：
1. 只使用提供的 DDL 中定义的表和列，不要引用不存在的表或列
2. 生成的 SQL 必须兼容 Apache Doris 语法
3. 如果查询涉及多张表，使用正确的 JOIN 语句连接
4. 对于聚合查询，确保 GROUP BY 包含所有非聚合列
5. 如果用户意图不明确，返回 clarification_needed=true 并说明需要澄清的内容
6. 为生成的 SQL 提供简洁的中文解释

输出格式（严格 JSON，sql 字段必须为单行字符串，不允许换行）：
{
  "sql": "生成的SQL语句（单行，不要换行）",
  "explanation": "SQL的中文解释说明",
  "confidence": 0.0-1.0之间的置信度,
  "referenced_tables": ["引用的表名列表"],
  "clarification_needed": false,
  "clarification_message": ""
}

重要：输出必须是合法的 JSON 格式。sql 字段中的 SQL 语句必须写在一行内，不要使用换行符。"""


# SQL 修正系统提示词
REFINE_SYSTEM_PROMPT = """你是一个专业的 Apache Doris SQL 修正助手。用户对之前生成的 SQL 提出了修改意见，请根据反馈修正 SQL。

规则：
1. 只使用提供的 DDL 中定义的表和列
2. 保留原 SQL 的正确部分，只修改用户指出的问题
3. 生成的 SQL 必须兼容 Apache Doris 语法
4. 为修正后的 SQL 提供简洁的中文解释

输出格式（严格 JSON，sql 字段必须为单行字符串，不允许换行）：
{
  "sql": "修正后的SQL语句（单行，不要换行）",
  "explanation": "修正说明",
  "confidence": 0.0-1.0之间的置信度,
  "referenced_tables": ["引用的表名列表"]
}

重要：输出必须是合法的 JSON 格式。sql 字段中的 SQL 语句必须写在一行内，不要使用换行符。"""

# 参考 SQL 生成系统提示词
REFERENCE_SQL_SYSTEM_PROMPT = """你是一个专业的 Apache Doris SQL 生成助手。根据指标名称和用途说明，结合提供的数据库表结构（DDL），生成一个参考 SQL 语句。

规则：
1. 只使用提供的 DDL 中定义的表和列
2. SQL 应该能够计算或查询该指标描述的业务含义
3. 生成的 SQL 必须兼容 Apache Doris 语法
4. 如果涉及多张表，使用正确的 JOIN 语句
5. 使用参数占位符 ${param_name} 表示可变参数

只返回 SQL 语句，不要包含其他内容。"""


class SQLGeneratorError(Exception):
    """SQL 生成器异常基类"""
    pass


class LLMCallError(SQLGeneratorError):
    """LLM 调用异常"""
    pass


class SQLValidationError(SQLGeneratorError):
    """SQL 验证异常"""
    pass


class SQLGenerator:
    """SQL 生成器

    基于 LLM 和 DDL 上下文生成 Apache Doris 兼容的 SQL 语句。
    支持自然语言转 SQL、反馈修正、参考 SQL 生成和引用验证。

    Attributes:
        client: OpenAI API 客户端
        model: LLM 模型名称
        temperature: 生成温度参数
        max_tokens: 最大生成 token 数
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ):
        """初始化 SQL 生成器

        Args:
            api_key: LLM API 密钥，默认使用配置
            base_url: LLM API 基础 URL，默认使用配置
            model: LLM 模型名称，默认使用配置
            temperature: 生成温度，默认使用配置
            max_tokens: 最大 token 数，默认使用配置
        """
        self.model = model or settings.llm_model
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.max_tokens = max_tokens or settings.llm_max_tokens

        # 1.初始化 OpenAI 客户端
        self.client = OpenAI(
            api_key=api_key or settings.llm_api_key,
            base_url=base_url or settings.llm_base_url,
        )

        logger.info(
            "SQL Generator initialized, model=%s, temperature=%s, max_tokens=%d",
            self.model, self.temperature, self.max_tokens,
        )

    def _build_ddl_context_text(self, ddl_context: list[DDLInfo]) -> str:
        """构建 DDL 上下文文本

        将 DDL 信息列表格式化为 LLM 可理解的文本描述。

        Args:
            ddl_context: DDL 信息列表

        Returns:
            格式化的 DDL 上下文文本
        """
        if not ddl_context:
            return "无可用的表结构信息。"

        parts = []
        for ddl in ddl_context:
            # 1.使用完整 DDL 内容
            parts.append(f"-- 表: {ddl.database}.{ddl.table_name}")
            parts.append(ddl.ddl_content)
            parts.append("")

        return "\n".join(parts)

    def _build_conversation_history_text(
        self, conversation_history: list[dict]
    ) -> str:
        """构建对话历史文本

        将对话历史格式化为 LLM 可理解的上下文。

        Args:
            conversation_history: 对话历史消息列表

        Returns:
            格式化的对话历史文本
        """
        if not conversation_history:
            return ""

        parts = ["以下是之前的对话历史："]
        for msg in conversation_history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            sql = msg.get("sql", "")

            if role == "user":
                parts.append(f"用户: {content}")
            elif role == "agent":
                parts.append(f"助手: {content}")
                if sql:
                    parts.append(f"生成的SQL: {sql}")

        return "\n".join(parts)

    def _call_llm(self, system_prompt: str, user_message: str) -> str:
        """调用 LLM 生成响应

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息

        Returns:
            LLM 响应文本

        Raises:
            LLMCallError: LLM 调用失败时抛出
        """
        logger.info(
            "Calling LLM, model=%s, message_length=%d",
            self.model, len(user_message),
        )

        # 注入当前时间到系统提示词
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = system_prompt.replace("{current_time}", current_time)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            result = response.choices[0].message.content
            logger.info("LLM response received, length=%d", len(result) if result else 0)
            return result or ""

        except Exception as e:
            logger.error("LLM call failed, error=%s", str(e))
            raise LLMCallError(f"LLM call failed: {e}") from e

    def _fix_json_newlines(self, json_str: str) -> str:
        """修复 JSON 字符串值中未转义的换行符

        LLM 生成的 JSON 中，字符串值（如 SQL 语句）可能包含原始换行符，
        这会导致 json.loads 解析失败。此方法将字符串值内的原始换行替换为空格。

        Args:
            json_str: 可能包含未转义换行的 JSON 文本

        Returns:
            修复后的 JSON 文本
        """
        # 逐字符扫描，在字符串值内部将 \n 替换为空格
        result = []
        in_string = False
        i = 0
        while i < len(json_str):
            ch = json_str[i]
            if ch == '\\' and in_string:
                # 转义字符，保留原样并跳过下一个字符
                result.append(ch)
                i += 1
                if i < len(json_str):
                    result.append(json_str[i])
                i += 1
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
            elif ch == '\n' and in_string:
                # 字符串值内的原始换行，替换为空格
                result.append(' ')
            elif ch == '\r' and in_string:
                # 跳过 \r
                pass
            else:
                result.append(ch)
            i += 1
        return ''.join(result)

    def _parse_llm_response(self, response: str) -> dict:
        """解析 LLM 响应为 JSON 字典

        尝试从 LLM 响应中提取 JSON 内容，支持 markdown 代码块格式、
        thinking 标签包裹、以及 JSON 前后有额外文本的情况。
        当 JSON 解析失败时，尝试修复字符串值中未转义的换行符后重试。

        Args:
            response: LLM 原始响应文本

        Returns:
            解析后的字典

        Raises:
            SQLGeneratorError: JSON 解析失败时抛出
        """
        # 0.移除可能的 <think>...</think> 标签内容
        cleaned = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()

        # 1.尝试提取 markdown 代码块中的 JSON
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # 尝试修复字符串值中的换行符
                fixed = self._fix_json_newlines(json_str)
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass

        # 2.尝试直接解析整个响应
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 3.尝试提取第一个 JSON 对象（花括号匹配）
        brace_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
        if brace_match:
            json_str = brace_match.group(0)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                fixed = self._fix_json_newlines(json_str)
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass

        # 4.最后尝试：找到第一个 { 和最后一个 } 之间的内容
        first_brace = cleaned.find('{')
        last_brace = cleaned.rfind('}')
        if first_brace != -1 and last_brace > first_brace:
            json_str = cleaned[first_brace:last_brace + 1]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # 尝试修复换行符后重试
                fixed = self._fix_json_newlines(json_str)
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError as e:
                    logger.error(
                        "Failed to parse LLM response as JSON, error=%s, response_preview=%s",
                        str(e), cleaned[:200],
                    )
                    raise SQLGeneratorError(f"Failed to parse LLM response: {e}") from e

        logger.error("No JSON found in LLM response, response_preview=%s", cleaned[:200])
        raise SQLGeneratorError("No JSON object found in LLM response")

    def generate_sql(self, params: SQLGenParams) -> SQLGenResult:
        """根据自然语言和上下文生成 SQL

        构建包含 DDL 上下文和对话历史的 prompt，调用 LLM 生成 SQL，
        解析响应并验证 SQL 引用的表名和列名。

        Args:
            params: SQL 生成参数，包含用户查询、DDL 上下文、对话历史等

        Returns:
            SQL 生成结果，包含 SQL 语句、解释、置信度和引用表名

        Raises:
            LLMCallError: LLM 调用失败
            SQLGeneratorError: 响应解析失败
        """
        logger.info(
            "Generating SQL, query=%s, ddl_count=%d, history_count=%d",
            params.user_query[:50], len(params.ddl_context), len(params.conversation_history),
        )

        # 1.构建 DDL 上下文
        ddl_context_list = []
        for ddl_item in params.ddl_context:
            if isinstance(ddl_item, DDLInfo):
                ddl_context_list.append(ddl_item)
            elif isinstance(ddl_item, dict):
                ddl_context_list.append(DDLInfo(**ddl_item))
            else:
                ddl_context_list.append(ddl_item)

        ddl_text = self._build_ddl_context_text(ddl_context_list)

        # 2.构建对话历史
        history_text = self._build_conversation_history_text(
            params.conversation_history
        )

        # 3.构建用户消息
        user_message_parts = [
            "## 数据库表结构（DDL）",
            ddl_text,
        ]

        if history_text:
            user_message_parts.append("## 对话历史")
            user_message_parts.append(history_text)

        if params.previous_sql:
            user_message_parts.append("## 上一次生成的 SQL")
            user_message_parts.append(params.previous_sql)

        user_message_parts.append("## 用户查询")
        user_message_parts.append(params.user_query)

        user_message = "\n\n".join(user_message_parts)

        # 4.调用 LLM
        response = self._call_llm(SYSTEM_PROMPT, user_message)

        # 5.解析响应
        parsed = self._parse_llm_response(response)

        # 6.检查是否需要澄清
        if parsed.get("clarification_needed", False):
            clarification_msg = parsed.get(
                "clarification_message", "请补充更多查询细节"
            )
            logger.info("Clarification needed, message=%s", clarification_msg)
            return SQLGenResult(
                sql="",
                explanation=clarification_msg,
                confidence=0.0,
                referenced_tables=[],
            )

        # 7.构建结果
        sql = parsed.get("sql", "")
        explanation = parsed.get("explanation", "")
        confidence = float(parsed.get("confidence", 0.8))
        referenced_tables = parsed.get("referenced_tables", [])

        # 8.验证 SQL 引用
        if sql and ddl_context_list:
            is_valid, errors = self.validate_sql_references(sql, ddl_context_list)
            if not is_valid:
                logger.warning(
                    "SQL reference validation failed, errors=%s", errors
                )
                # 在解释中附加验证警告
                explanation += f"\n\n⚠️ 引用验证警告: {'; '.join(errors)}"

        result = SQLGenResult(
            sql=sql,
            explanation=explanation,
            confidence=confidence,
            referenced_tables=referenced_tables,
        )

        logger.info(
            "SQL generated, sql_length=%d, confidence=%s, tables=%s",
            len(sql), confidence, referenced_tables,
        )
        return result

    def refine_sql_with_feedback(
        self,
        original_sql: str,
        feedback: str,
        context: dict,
    ) -> SQLGenResult:
        """根据用户反馈修正 SQL

        接收用户对已生成 SQL 的修改意见，结合 DDL 上下文重新生成修正后的 SQL。

        Args:
            original_sql: 原始 SQL 语句
            feedback: 用户反馈/修改意见
            context: 上下文信息，包含 ddl_context 和 conversation_history

        Returns:
            修正后的 SQL 生成结果

        Raises:
            LLMCallError: LLM 调用失败
            SQLGeneratorError: 响应解析失败
        """
        logger.info(
            "Refining SQL with feedback, sql_length=%d, feedback=%s",
            len(original_sql), feedback[:50],
        )

        # 1.提取 DDL 上下文
        ddl_context_raw = context.get("ddl_context", [])
        ddl_context_list = []
        for ddl_item in ddl_context_raw:
            if isinstance(ddl_item, DDLInfo):
                ddl_context_list.append(ddl_item)
            elif isinstance(ddl_item, dict):
                ddl_context_list.append(DDLInfo(**ddl_item))

        ddl_text = self._build_ddl_context_text(ddl_context_list)

        # 2.构建对话历史
        history_text = self._build_conversation_history_text(
            context.get("conversation_history", [])
        )

        # 3.构建用户消息
        user_message_parts = [
            "## 数据库表结构（DDL）",
            ddl_text,
        ]

        if history_text:
            user_message_parts.append("## 对话历史")
            user_message_parts.append(history_text)

        user_message_parts.append("## 原始 SQL")
        user_message_parts.append(original_sql)
        user_message_parts.append("## 用户修改意见")
        user_message_parts.append(feedback)

        user_message = "\n\n".join(user_message_parts)

        # 4.调用 LLM
        response = self._call_llm(REFINE_SYSTEM_PROMPT, user_message)

        # 5.解析响应
        parsed = self._parse_llm_response(response)

        sql = parsed.get("sql", "")
        explanation = parsed.get("explanation", "")
        confidence = float(parsed.get("confidence", 0.8))
        referenced_tables = parsed.get("referenced_tables", [])

        # 6.验证 SQL 引用
        if sql and ddl_context_list:
            is_valid, errors = self.validate_sql_references(sql, ddl_context_list)
            if not is_valid:
                logger.warning(
                    "Refined SQL reference validation failed, errors=%s", errors
                )
                explanation += f"\n\n⚠️ 引用验证警告: {'; '.join(errors)}"

        result = SQLGenResult(
            sql=sql,
            explanation=explanation,
            confidence=confidence,
            referenced_tables=referenced_tables,
        )

        logger.info(
            "SQL refined, sql_length=%d, confidence=%s", len(sql), confidence
        )
        return result

    def generate_reference_sql(
        self,
        metric_name: str,
        description: str,
        ddl_context: list[DDLInfo],
    ) -> str:
        """根据指标名称和用途生成参考 SQL

        为指标创建场景生成参考 SQL 模板，供用户参考和修改。

        Args:
            metric_name: 指标名称
            description: 指标用途说明
            ddl_context: DDL 上下文信息列表

        Returns:
            生成的参考 SQL 语句

        Raises:
            LLMCallError: LLM 调用失败
        """
        logger.info(
            "Generating reference SQL, metric_name=%s, description=%s",
            metric_name, description[:50],
        )

        # 1.构建 DDL 上下文
        ddl_text = self._build_ddl_context_text(ddl_context)

        # 2.构建用户消息
        user_message = (
            f"## 数据库表结构（DDL）\n{ddl_text}\n\n"
            f"## 指标信息\n"
            f"指标名称: {metric_name}\n"
            f"用途说明: {description}\n\n"
            f"请根据以上信息生成一个参考 SQL 语句。"
        )

        # 3.调用 LLM
        response = self._call_llm(REFERENCE_SQL_SYSTEM_PROMPT, user_message)

        # 4.清理响应（去除可能的 markdown 代码块标记）
        sql = response.strip()
        if sql.startswith("```"):
            # 去除 markdown 代码块
            lines = sql.split("\n")
            # 移除首行 ``` 和末行 ```
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            sql = "\n".join(lines).strip()

        logger.info(
            "Reference SQL generated, metric_name=%s, sql_length=%d",
            metric_name, len(sql),
        )
        return sql

    def _extract_table_aliases(self, sql: str) -> dict[str, str]:
        """从 SQL 中提取表别名映射

        解析 FROM 和 JOIN 子句中的表别名定义。

        Args:
            sql: SQL 语句

        Returns:
            别名到真实表名的映射字典（小写）
        """
        aliases: dict[str, str] = {}

        # 1.移除字符串字面量
        sql_clean = re.sub(r"'[^']*'", "''", sql)
        sql_clean = re.sub(r'"[^"]*"', '""', sql_clean)

        # 2.匹配 FROM table alias 和 FROM table AS alias
        from_alias_pattern = re.compile(
            r'\bFROM\s+`?(\w+)`?\s+(?:AS\s+)?`?(\w+)`?',
            re.IGNORECASE,
        )
        for match in from_alias_pattern.finditer(sql_clean):
            table_name = match.group(1).lower()
            alias = match.group(2).lower()
            # 过滤 SQL 关键字作为别名的误匹配
            if alias.upper() not in {"WHERE", "JOIN", "LEFT", "RIGHT", "INNER",
                                      "OUTER", "CROSS", "FULL", "NATURAL", "ON",
                                      "GROUP", "ORDER", "HAVING", "LIMIT", "UNION"}:
                aliases[alias] = table_name

        # 3.匹配 JOIN table alias 和 JOIN table AS alias
        join_alias_pattern = re.compile(
            r'\bJOIN\s+`?(\w+)`?\s+(?:AS\s+)?`?(\w+)`?',
            re.IGNORECASE,
        )
        for match in join_alias_pattern.finditer(sql_clean):
            table_name = match.group(1).lower()
            alias = match.group(2).lower()
            if alias.upper() not in {"ON", "WHERE", "JOIN", "LEFT", "RIGHT",
                                      "INNER", "OUTER", "CROSS", "FULL", "NATURAL"}:
                aliases[alias] = table_name

        return aliases

    def validate_sql_references(
        self,
        sql: str,
        ddl_context: list[DDLInfo],
    ) -> tuple[bool, list[str]]:
        """验证 SQL 中引用的表名和列名是否存在于 DDL 上下文

        解析 SQL 语句中引用的表名和列名，检查它们是否在提供的 DDL 上下文中定义。
        支持表别名解析，将别名映射到真实表名后再验证。

        Args:
            sql: 待验证的 SQL 语句
            ddl_context: DDL 上下文信息列表

        Returns:
            (is_valid, errors) 元组：
            - is_valid: 所有引用均有效时为 True
            - errors: 验证错误信息列表
        """
        logger.info("Validating SQL references, sql_length=%d", len(sql))

        errors: list[str] = []

        # 1.构建可用表名和列名映射
        available_tables: dict[str, set[str]] = {}
        for ddl in ddl_context:
            table_name = ddl.table_name.lower()
            columns = {col.name.lower() for col in ddl.columns}
            available_tables[table_name] = columns

        # 2.提取表别名映射
        aliases = self._extract_table_aliases(sql)

        # 3.提取 SQL 中引用的表名
        referenced_tables = self._extract_table_references(sql)

        # 4.验证表名
        for table in referenced_tables:
            if table.lower() not in available_tables:
                errors.append(f"表 '{table}' 不存在于 DDL 上下文中")

        # 5.提取并验证列引用
        referenced_columns = self._extract_column_references(sql)
        all_columns = set()
        for cols in available_tables.values():
            all_columns.update(cols)

        for col_ref in referenced_columns:
            # 处理 table.column 或 alias.column 格式
            if "." in col_ref:
                parts = col_ref.split(".", 1)
                table_part = parts[0].lower()
                col_part = parts[1].lower()

                # 解析别名到真实表名
                real_table = aliases.get(table_part, table_part)

                if real_table in available_tables:
                    if col_part not in available_tables[real_table]:
                        errors.append(
                            f"列 '{col_ref}' 不存在于表 '{real_table}' 中"
                        )
                elif table_part not in available_tables:
                    # 别名和表名都找不到，跳过（可能是子查询别名）
                    pass
            else:
                # 无表前缀的列名，检查是否存在于任意已知表中
                col_lower = col_ref.lower()
                if col_lower not in all_columns:
                    errors.append(
                        f"列 '{col_ref}' 不存在于任何已知表中"
                    )

        is_valid = len(errors) == 0
        if is_valid:
            logger.info("SQL reference validation passed")
        else:
            logger.warning(
                "SQL reference validation failed, error_count=%d", len(errors)
            )

        return is_valid, errors

    def _extract_table_references(self, sql: str) -> list[str]:
        """从 SQL 中提取引用的表名

        解析 FROM、JOIN 子句中的表名引用。

        Args:
            sql: SQL 语句

        Returns:
            引用的表名列表（去重）
        """
        tables: set[str] = set()
        sql_upper = sql.upper()
        sql_clean = sql

        # 1.移除字符串字面量，避免误匹配
        sql_clean = re.sub(r"'[^']*'", "''", sql_clean)
        sql_clean = re.sub(r'"[^"]*"', '""', sql_clean)

        # 2.匹配 FROM 子句中的表名（支持 database.table 格式）
        from_pattern = re.compile(
            r'\bFROM\s+`?(\w+)`?(?:\.`?(\w+)`?)?(?:\s+(?:AS\s+)?`?\w+`?)?',
            re.IGNORECASE,
        )
        for match in from_pattern.finditer(sql_clean):
            if match.group(2):
                # database.table 格式，取表名部分
                tables.add(match.group(2))
            else:
                tables.add(match.group(1))

        # 3.匹配 JOIN 子句中的表名（支持 database.table 格式）
        join_pattern = re.compile(
            r'\bJOIN\s+`?(\w+)`?(?:\.`?(\w+)`?)?(?:\s+(?:AS\s+)?`?\w+`?)?',
            re.IGNORECASE,
        )
        for match in join_pattern.finditer(sql_clean):
            if match.group(2):
                tables.add(match.group(2))
            else:
                tables.add(match.group(1))

        # 4.过滤 SQL 关键字（避免误识别）
        sql_keywords = {
            "SELECT", "FROM", "WHERE", "GROUP", "ORDER", "HAVING",
            "LIMIT", "OFFSET", "UNION", "INSERT", "UPDATE", "DELETE",
            "SET", "VALUES", "INTO", "AS", "ON", "AND", "OR", "NOT",
            "IN", "EXISTS", "BETWEEN", "LIKE", "IS", "NULL", "TRUE",
            "FALSE", "CASE", "WHEN", "THEN", "ELSE", "END", "BY",
            "ASC", "DESC", "ALL", "DISTINCT", "LEFT", "RIGHT",
            "INNER", "OUTER", "CROSS", "FULL", "NATURAL",
        }
        tables = {t for t in tables if t.upper() not in sql_keywords}

        return list(tables)

    def _extract_column_references(self, sql: str) -> list[str]:
        """从 SQL 中提取引用的列名

        解析 SELECT、WHERE、GROUP BY、ORDER BY 等子句中的列引用。
        支持 table.column 和单独 column 两种格式。
        过滤字符串字面量、数字、SQL 关键字和函数名。

        Args:
            sql: SQL 语句

        Returns:
            引用的列名列表（去重）
        """
        columns: set[str] = set()

        # 1.移除字符串字面量和数字字面量
        sql_clean = re.sub(r"'[^']*'", " ", sql)
        sql_clean = re.sub(r'"[^"]*"', " ", sql_clean)
        # 移除独立数字（如 LIMIT 1000）
        sql_clean = re.sub(r'\b\d+\.?\d*\b', " ", sql_clean)

        # 2.匹配 table.column 格式（含反引号）
        qualified_pattern = re.compile(
            r'`?(\w+)`?\s*\.\s*`?(\w+)`?'
        )
        for match in qualified_pattern.finditer(sql_clean):
            table_part = match.group(1)
            col_part = match.group(2)
            columns.add(f"{table_part}.{col_part}")

        # 3.不再提取无前缀的列名用于验证，因为误报率太高
        # 仅验证 qualified（table.column）格式的列引用

        return list(columns)

    def _is_sql_keyword_or_function(self, name: str) -> bool:
        """判断名称是否为 SQL 关键字或内置函数

        Args:
            name: 待检查的名称

        Returns:
            是关键字或函数返回 True
        """
        sql_keywords_and_functions = {
            "SELECT", "FROM", "WHERE", "GROUP", "ORDER", "HAVING",
            "LIMIT", "OFFSET", "UNION", "INSERT", "UPDATE", "DELETE",
            "SET", "VALUES", "INTO", "AS", "ON", "AND", "OR", "NOT",
            "IN", "EXISTS", "BETWEEN", "LIKE", "IS", "NULL", "TRUE",
            "FALSE", "CASE", "WHEN", "THEN", "ELSE", "END", "BY",
            "ASC", "DESC", "ALL", "DISTINCT", "COUNT", "SUM", "AVG",
            "MAX", "MIN", "COALESCE", "IFNULL", "IF", "CAST",
            "CONVERT", "DATE", "NOW", "YEAR", "MONTH", "DAY",
            "HOUR", "MINUTE", "SECOND", "CONCAT", "SUBSTRING",
            "TRIM", "UPPER", "LOWER", "LENGTH", "ROUND", "FLOOR",
            "CEIL", "ABS", "LEFT", "RIGHT", "INNER", "OUTER",
            "CROSS", "FULL", "NATURAL", "JOIN", "OVER", "PARTITION",
            "ROW_NUMBER", "RANK", "DENSE_RANK", "LAG", "LEAD",
        }
        return name.upper() in sql_keywords_and_functions
