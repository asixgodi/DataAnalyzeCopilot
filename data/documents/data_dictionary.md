# 数据字段说明

## products 商品表
| 字段 | 类型 | 说明 |
| id | INTEGER | 商品ID |
| name | TEXT | 商品名称 |
| category | TEXT | 类目（服装/鞋靴/数码） |
| price | REAL | 售价（元） |

## orders 订单表
| 字段 | 类型 | 说明 |
| id | INTEGER | 订单ID |
| product_id | INTEGER | 关联商品ID |
| month | TEXT | 订单月份（YYYY-MM） |
| quantity | INTEGER | 购买数量 |
| amount | REAL | 订单金额（元） |

## refunds 退款表
| 字段 | 类型 | 说明 |
| id | INTEGER | 退款ID |
| order_id | INTEGER | 关联订单ID |
| reason | TEXT | 退款原因 |
| status | TEXT | 退款状态（approved/pending/rejected） |
| refund_amount | REAL | 退款金额（元） |

## reviews 评价表
| 字段 | 类型 | 说明 |
| id | INTEGER | 评价ID |
| product_id | INTEGER | 关联商品ID |
| rating | INTEGER | 评分（1-5） |
| content | TEXT | 评价内容 |
| month | TEXT | 评价月份 |

## tickets 客服工单表
| 字段 | 类型 | 说明 |
| id | INTEGER | 工单ID |
| product_id | INTEGER | 关联商品ID |
| category | TEXT | 工单分类 |
| reason | TEXT | 工单原因 |
| priority | TEXT | 优先级（P0/P1/P2/P3） |
| month | TEXT | 工单月份 |
