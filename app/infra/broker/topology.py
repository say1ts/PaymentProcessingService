from faststream.rabbit import RabbitExchange, RabbitQueue
from faststream.rabbit.schemas import ExchangeType

dlx = RabbitExchange(
    name="payments.dlx",
    type=ExchangeType.FANOUT,
    durable=True,
)

dead_queue = RabbitQueue(
    name="payments.dead",
    durable=True,
    bind_arguments={
        "exchange": "payments.dlx",
        "routing_key": "#",
    }
)

payments_exchange = RabbitExchange(
    name="payments.exchange",
    type=ExchangeType.DIRECT,
    durable=True,
)

payments_queue = RabbitQueue(
    name="payments.new",
    durable=True,
    routing_key="payment.created",
    arguments={
        "x-dead-letter-exchange": "payments.dlx",
    },
)
