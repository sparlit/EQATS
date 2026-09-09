use alloy::{
    network::Ethereum, primitives::address, providers::DynProvider, transports::TransportError,
};

use crate::hyperevm::{
    Provider,
    uniswap::{self, Contracts},
};

/// Prjx contracts
pub static CONTRACTS: Contracts = Contracts {
    factory: address!("0xFf7B3e8C00e57ea31477c32A5B52a58Eea47b072"),
    non_fungible_position_manager: address!("0xeaD19AE861c29bBb2101E834922B2FEee69B9091"),
    swap_router: address!("0x1EbDFC75FfE3ba3de61E7138a3E8706aC841Af9B"),
    quoter: address!("0x239F11a7A3E08f2B8110D4CA9F6B95d4c8865258"),
};

/// Creates a prjx client from a provider.
pub fn from_provider<P: Provider>(provider: P) -> uniswap::Client<P> {
    uniswap::Client::new(provider, CONTRACTS)
}

/// Creates a uniswap client for prjx.com
pub async fn mainnet() -> Result<uniswap::Client<DynProvider<Ethereum>>, TransportError> {
    uniswap::Client::mainnet(CONTRACTS).await
}

/// Creates a uniswap client for prjx.com
pub async fn mainnet_with_url(
    url: &str,
) -> Result<uniswap::Client<DynProvider<Ethereum>>, TransportError> {
    uniswap::Client::mainnet_with_url(url, CONTRACTS).await
}

#[cfg(test)]
mod tests {
    use alloy::primitives::{Address, address};

    use super::*;
    use crate::hyperevm::{
        self,
        uniswap::{FEES, sqrt_price_limit_x96},
    };

    const UBTC_ADDRESS: Address = address!("0x9fdbda0a5e284c32744d2f17ee5c74b284993463");
    // const USDT_ADDRESS: Address = address!("0xb8ce59fc3717ada4c02eadf9682a9e934f625ebb");

    #[tokio::test]
    async fn test_pool() {
        let client = mainnet().await.unwrap();
        let addy = client
            .get_pool_address(hyperevm::WHYPE_ADDRESS, UBTC_ADDRESS, 3000)
            .await
            .unwrap();
        assert_eq!(addy, address!("0x0D6ECB912b6ee160e95Bc198b618Acc1bCb92525"))
    }

    #[tokio::test]
    async fn test_pool_price() {
        let client = mainnet().await.unwrap();
        let price = client
            .get_pool_price(
                hyperevm::WHYPE_ADDRESS,
                UBTC_ADDRESS,
                FEES[2], /* 3000 */
            )
            .await
            .unwrap();
        println!("<< {price}");
        println!(">> {}", sqrt_price_limit_x96(price, price.scale()));
        // assert_eq!(addy, address!(""))
    }

    #[tokio::test]
    async fn test_positions() {
        let client = mainnet().await.unwrap();
        let positions = client
            .positions(address!("0x3beB0613a3A920402fee4A1f5e5Ba4126f91764f"))
            .await
            .unwrap();
        println!("{positions:?}");
    }
}